import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import psutil
import threading
import time
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
import logging
from logging.handlers import TimedRotatingFileHandler

class PortMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("Windows端口监控服务管理器 v2.0")
        self.root.geometry("950x700")
        
        # 配置文件路径
        self.config_file = "config.json"
        self.monitored_ports = {}  # {端口: 脚本路径}
        self.monitoring = False
        self.monitor_thread = None
        self.monitor_interval = 5
        self.log_keep_days = 30
        self.max_retry_count = 3
        self.retry_interval = 30
        
        # 初始化统计变量
        self.restart_today = 0
        self.restart_total = 0
        self.port_stats = {}
        self.last_reset_day = datetime.now().day
        self.port_status = {}
        self.port_retry_info = {}
        
        # 初始化控件变量
        self.auto_start_var = tk.BooleanVar(value=False)
        
        # 初始化日志系统
        self.setup_logging()
        
        # 加载配置
        self.load_config()
        
        # 创建界面
        self.create_widgets()
        
        # 清理旧日志
        self.clean_old_logs()
        
        # 启动监控线程（如果设置了自动启动）
        if self.auto_start_var.get():
            self.start_monitoring()
        
        # 定时清理日志
        self.schedule_log_cleanup()
        
    def setup_logging(self):
        """设置日志系统"""
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        self.logger = logging.getLogger('PortMonitor')
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        
        # 文件处理器
        log_file = os.path.join(log_dir, 'port_monitor.log')
        file_handler = TimedRotatingFileHandler(
            log_file, 
            when='midnight', 
            interval=1, 
            backupCount=self.log_keep_days,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # 脚本执行日志文件
        self.script_log_file = os.path.join(log_dir, 'script_execution.log')
        
    def log_script_execution(self, port, command, output, error, success):
        """记录脚本执行日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"""
{'='*60}
时间: {timestamp}
端口: {port}
命令: {command}
状态: {'成功' if success else '失败'}
输出: {output if output else '无'}
错误: {error if error else '无'}
{'='*60}
"""
        try:
            with open(self.script_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            self.logger.error(f"写入脚本日志失败: {str(e)}")
            
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)
        
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        self.create_monitor_tab()
        self.create_settings_tab()
        self.create_log_tab()
        self.create_about_tab()
        
    def create_monitor_tab(self):
        monitor_tab = ttk.Frame(self.notebook)
        self.notebook.add(monitor_tab, text="端口监控")
        
        self.create_port_management_frame(monitor_tab)
        self.create_monitor_status_frame(monitor_tab)
        self.create_realtime_log_frame(monitor_tab)
        
        monitor_tab.columnconfigure(0, weight=1)
        monitor_tab.rowconfigure(2, weight=1)
        
    def create_port_management_frame(self, parent):
        port_frame = ttk.LabelFrame(parent, text="端口与脚本关联管理", padding="10")
        port_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        
        add_frame = ttk.Frame(port_frame)
        add_frame.grid(row=0, column=0, columnspan=6, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(add_frame, text="端口号:").grid(row=0, column=0, padx=5)
        self.port_entry = ttk.Entry(add_frame, width=10)
        self.port_entry.grid(row=0, column=1, padx=5)
        
        ttk.Label(add_frame, text="重启脚本:").grid(row=0, column=2, padx=5)
        self.script_path_var = tk.StringVar()
        self.script_entry = ttk.Entry(add_frame, textvariable=self.script_path_var, width=40)
        self.script_entry.grid(row=0, column=3, padx=5)
        
        ttk.Button(add_frame, text="浏览", command=self.browse_script).grid(row=0, column=4, padx=2)
        ttk.Button(add_frame, text="添加/更新", command=self.add_port_mapping).grid(row=0, column=5, padx=2)
        
        info_label = ttk.Label(port_frame, text="说明：程序会持续监控这些端口，如果发现端口没有进程占用，则执行关联的重启脚本", foreground="gray")
        info_label.grid(row=1, column=0, columnspan=6, sticky=tk.W, pady=5)
        
        list_frame = ttk.Frame(port_frame)
        list_frame.grid(row=2, column=0, columnspan=6, sticky=(tk.W, tk.E), pady=10)
        
        columns = ('端口', '关联脚本', '当前状态', '失败次数', '最后重启时间', '重启次数')
        self.port_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=8)
        
        col_widths = {'端口': 80, '关联脚本': 250, '当前状态': 100, '失败次数': 80, '最后重启时间': 150, '重启次数': 80}
        for col in columns:
            self.port_tree.heading(col, text=col)
            self.port_tree.column(col, width=col_widths.get(col, 100))
        
        tree_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.port_tree.yview)
        self.port_tree.configure(yscrollcommand=tree_scrollbar.set)
        
        self.port_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        btn_frame = ttk.Frame(port_frame)
        btn_frame.grid(row=3, column=0, columnspan=6, pady=5)
        
        ttk.Button(btn_frame, text="删除选中", command=self.remove_port_mapping).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="批量导入", command=self.batch_import).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="导出配置", command=self.export_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="测试脚本", command=self.test_script).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="立即检测", command=self.scan_ports_now).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="重置失败计数", command=self.reset_failed_ports).pack(side=tk.LEFT, padx=5)
        
        port_frame.columnconfigure(0, weight=1)
        self.update_port_tree()
        
    def create_monitor_status_frame(self, parent):
        monitor_frame = ttk.LabelFrame(parent, text="监控状态", padding="10")
        monitor_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        row1_frame = ttk.Frame(monitor_frame)
        row1_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.monitor_status = tk.StringVar(value="监控未启动")
        status_label = ttk.Label(row1_frame, textvariable=self.monitor_status, font=('Arial', 10, 'bold'))
        status_label.pack(side=tk.LEFT, padx=5)
        
        self.start_stop_btn = ttk.Button(row1_frame, text="启动监控", command=self.toggle_monitoring)
        self.start_stop_btn.pack(side=tk.LEFT, padx=5)
        
        row2_frame = ttk.Frame(monitor_frame)
        row2_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.stats_label = ttk.Label(row2_frame, text="统计: 监控0个端口 | 今日重启0次 | 总重启0次 | 失败0次")
        self.stats_label.pack(side=tk.LEFT, padx=5)
        
        row3_frame = ttk.Frame(monitor_frame)
        row3_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.port_status_label = ttk.Label(row3_frame, text="端口占用状态: 等待检测...", foreground="blue")
        self.port_status_label.pack(side=tk.LEFT, padx=5)
        
        row4_frame = ttk.Frame(monitor_frame)
        row4_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.disabled_label = ttk.Label(row4_frame, text="已禁用端口: 无", foreground="gray")
        self.disabled_label.pack(side=tk.LEFT, padx=5)
        
        monitor_frame.columnconfigure(0, weight=1)
        
    def create_realtime_log_frame(self, parent):
        log_frame = ttk.LabelFrame(parent, text="实时日志", padding="10")
        log_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        text_frame = ttk.Frame(log_frame)
        text_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.log_text = tk.Text(text_frame, height=12, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        log_scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        
        btn_frame = ttk.Frame(log_frame)
        btn_frame.grid(row=1, column=0, pady=5)
        
        ttk.Button(btn_frame, text="清空显示", command=self.clear_log_display).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="打开日志文件夹", command=self.open_log_folder).pack(side=tk.LEFT, padx=5)
        
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        
    def create_settings_tab(self):
        settings_tab = ttk.Frame(self.notebook)
        self.notebook.add(settings_tab, text="系统设置")
        
        monitor_settings = ttk.LabelFrame(settings_tab, text="监控设置", padding="10")
        monitor_settings.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=10, padx=10)
        
        ttk.Label(monitor_settings, text="监控频率(秒):").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.interval_var = tk.StringVar(value=str(self.monitor_interval))
        interval_spinbox = ttk.Spinbox(monitor_settings, from_=1, to=60, textvariable=self.interval_var, width=10)
        interval_spinbox.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(monitor_settings, text="应用", command=self.apply_interval).grid(row=0, column=2, padx=5)
        
        retry_frame = ttk.Frame(monitor_settings)
        retry_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        ttk.Label(retry_frame, text="最大重试次数:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.max_retry_var = tk.StringVar(value=str(self.max_retry_count))
        retry_spinbox = ttk.Spinbox(retry_frame, from_=1, to=10, textvariable=self.max_retry_var, width=10)
        retry_spinbox.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(retry_frame, text="重试间隔(秒):").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.retry_interval_var = tk.StringVar(value=str(self.retry_interval))
        retry_interval_spinbox = ttk.Spinbox(retry_frame, from_=5, to=300, textvariable=self.retry_interval_var, width=10)
        retry_interval_spinbox.grid(row=0, column=3, padx=5, pady=5)
        
        ttk.Button(retry_frame, text="应用重试设置", command=self.apply_retry_settings).grid(row=0, column=4, padx=5)
        
        self.auto_start_var = tk.BooleanVar(value=self.auto_start_var.get())
        ttk.Checkbutton(monitor_settings, text="程序启动时自动监控", variable=self.auto_start_var).grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky=tk.W)
        
        log_settings = ttk.LabelFrame(settings_tab, text="日志设置", padding="10")
        log_settings.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=10, padx=10)
        
        ttk.Label(log_settings, text="日志保存天数:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.log_keep_days_var = tk.StringVar(value=str(self.log_keep_days))
        log_days_spinbox = ttk.Spinbox(log_settings, from_=1, to=365, textvariable=self.log_keep_days_var, width=10)
        log_days_spinbox.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(log_settings, text="应用", command=self.apply_log_settings).grid(row=0, column=2, padx=5)
        
        ttk.Label(log_settings, text="日志文件位置: logs\\port_monitor.log").grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky=tk.W)
        ttk.Label(log_settings, text="脚本执行日志: logs\\script_execution.log").grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky=tk.W)
        
        settings_tab.columnconfigure(0, weight=1)
        
    def create_log_tab(self):
        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text="日志查看")
        
        select_frame = ttk.Frame(log_tab)
        select_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5, padx=5)
        
        ttk.Label(select_frame, text="选择日志类型:").grid(row=0, column=0, padx=5)
        self.log_type_var = tk.StringVar(value="monitor")
        ttk.Radiobutton(select_frame, text="监控日志", variable=self.log_type_var, value="monitor", command=self.refresh_log_files_list).grid(row=0, column=1, padx=5)
        ttk.Radiobutton(select_frame, text="脚本执行日志", variable=self.log_type_var, value="script", command=self.refresh_log_files_list).grid(row=0, column=2, padx=5)
        
        list_frame = ttk.Frame(log_tab)
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5, padx=5)
        
        ttk.Label(list_frame, text="日志文件列表:").grid(row=0, column=0, sticky=tk.W, pady=5)
        
        self.log_files_listbox = tk.Listbox(list_frame, height=8)
        self.log_files_listbox.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        log_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.log_files_listbox.yview)
        log_scrollbar.grid(row=1, column=1, sticky=(tk.N, tk.S))
        self.log_files_listbox.configure(yscrollcommand=log_scrollbar.set)
        
        ttk.Button(list_frame, text="刷新列表", command=self.refresh_log_files_list).grid(row=2, column=0, pady=5)
        
        content_frame = ttk.LabelFrame(log_tab, text="日志内容", padding="10")
        content_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5, padx=5)
        
        self.log_content_text = tk.Text(content_frame, height=15, wrap=tk.WORD)
        self.log_content_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        content_scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=self.log_content_text.yview)
        content_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_content_text.configure(yscrollcommand=content_scrollbar.set)
        
        btn_frame = ttk.Frame(content_frame)
        btn_frame.grid(row=1, column=0, pady=5)
        
        ttk.Button(btn_frame, text="查看选中日志", command=self.view_selected_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="删除选中日志", command=self.delete_selected_log).pack(side=tk.LEFT, padx=5)
        
        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(2, weight=1)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(1, weight=1)
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)
        
        self.refresh_log_files_list()
        
    def create_about_tab(self):
        about_tab = ttk.Frame(self.notebook)
        self.notebook.add(about_tab, text="关于")
        
        about_frame = ttk.Frame(about_tab)
        about_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
        
        title_label = ttk.Label(about_frame, text="Windows端口监控服务管理器", font=('Arial', 16, 'bold'))
        title_label.pack(pady=10)
        
        version_label = ttk.Label(about_frame, text="版本 2.0", font=('Arial', 10))
        version_label.pack(pady=5)
        
        info_text = """
功能说明：
• 监控指定端口是否有进程占用
• 如果端口空闲（无进程占用），自动执行重启脚本
• 支持重启失败重试机制
• 达到最大重试次数后自动停止监控该端口

使用说明：
1. 添加要监控的端口号
2. 关联重启脚本（当端口空闲时执行）
3. 设置监控频率和重试参数
4. 启动监控开始监听端口状态

重启脚本编写：
• 脚本接收3个参数：端口号、进程PID、服务名称
• Python脚本示例：python script.py 8080 1234 Tomcat
• 批处理脚本示例：script.bat 8080 1234 Tomcat

重试机制：
• 最大重试次数：端口空闲后最多尝试重启次数
• 重试间隔：每次重试之间的等待时间
• 达到上限后自动停止监控，需手动重置

技术支持：
• 日志文件保存在 logs 目录
• 配置文件为 config.json
        """
        
        info_label = ttk.Label(about_frame, text=info_text, justify=tk.LEFT)
        info_label.pack(pady=10)
        
    def browse_script(self):
        file_path = filedialog.askopenfilename(
            title="选择重启脚本",
            filetypes=[("Python文件", "*.py"), ("批处理文件", "*.bat"), ("可执行文件", "*.exe"), ("所有文件", "*.*")]
        )
        if file_path:
            self.script_path_var.set(file_path)
            
    def add_port_mapping(self):
        try:
            port = int(self.port_entry.get().strip())
            script_path = self.script_path_var.get().strip()
            
            if port < 1 or port > 65535:
                messagebox.showerror("错误", "端口号必须在1-65535之间")
                return
                
            if not script_path:
                messagebox.showerror("错误", "请选择关联的重启脚本")
                return
                
            if not os.path.exists(script_path):
                messagebox.showerror("错误", f"脚本文件不存在: {script_path}")
                return
                
            self.monitored_ports[port] = script_path
            
            if port not in self.port_stats:
                self.port_stats[port] = {'restart_count': 0, 'last_restart': None}
            
            if port not in self.port_retry_info:
                self.port_retry_info[port] = {'fail_count': 0, 'last_fail_time': None, 'is_disabled': False}
            
            if port not in self.port_status:
                self.port_status[port] = False
                
            self.update_port_tree()
            self.save_config()
            self.log_message(f"添加/更新端口关联: {port} -> {os.path.basename(script_path)}")
            
            self.port_entry.delete(0, tk.END)
            self.script_path_var.set("")
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的端口号")
            
    def remove_port_mapping(self):
        selection = self.port_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要删除的端口")
            return
            
        port = int(self.port_tree.item(selection[0])['values'][0])
        
        if messagebox.askyesno("确认删除", f"确定要删除端口 {port} 的监控配置吗？"):
            if port in self.monitored_ports:
                del self.monitored_ports[port]
                if port in self.port_status:
                    del self.port_status[port]
                if port in self.port_retry_info:
                    del self.port_retry_info[port]
                if port in self.port_stats:
                    del self.port_stats[port]
                    
                self.update_port_tree()
                self.save_config()
                self.log_message(f"删除端口关联: {port}")
                
                if len(self.monitored_ports) == 0 and self.monitoring:
                    self.stop_monitoring()
                    self.log_message("所有端口已删除，监控已自动停止")
                    
    def test_script(self):
        selection = self.port_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先在列表中选择要测试的端口")
            return
            
        port = int(self.port_tree.item(selection[0])['values'][0])
        script_path = self.monitored_ports.get(port)
        
        if not script_path:
            messagebox.showerror("错误", f"端口 {port} 未关联脚本")
            return
            
        if not os.path.exists(script_path):
            messagebox.showerror("错误", f"脚本文件不存在: {script_path}")
            return
            
        self.log_message(f"开始测试端口 {port} 的脚本: {os.path.basename(script_path)}")
        
        result = messagebox.askyesno("测试脚本", f"即将测试执行脚本:\n{script_path}\n\n是否继续？")
        
        if result:
            success = self.execute_restart_script(port, {'pid': 0, 'name': 'Test'})
            
            if success:
                messagebox.showinfo("测试结果", f"脚本执行成功！\n\n请查看日志了解详细信息。")
                self.log_message(f"端口 {port} 脚本测试成功")
            else:
                messagebox.showerror("测试结果", f"脚本执行失败！\n\n请查看日志了解详细错误信息。")
                self.log_message(f"端口 {port} 脚本测试失败")
                
    def scan_ports_now(self):
        self.log_message("开始扫描所有监控端口...")
        for port in self.monitored_ports.keys():
            self.check_port_status(port)
        self.log_message("端口扫描完成")
        self.update_port_status_display()
        
    def reset_failed_ports(self):
        reset_count = 0
        for port in list(self.port_retry_info.keys()):
            if self.port_retry_info[port].get('is_disabled', False):
                self.port_retry_info[port]['is_disabled'] = False
                self.port_retry_info[port]['fail_count'] = 0
                reset_count += 1
                self.log_message(f"已重置端口 {port} 的失败状态，恢复监控")
        
        if reset_count > 0:
            self.update_port_tree()
            self.update_disabled_ports_display()
            messagebox.showinfo("成功", f"已重置 {reset_count} 个端口的失败状态")
        else:
            messagebox.showinfo("提示", "没有需要重置的端口")
        
    def check_port_status(self, port):
        process_info = self.get_process_by_port(port)
        is_occupied = process_info is not None
        self.port_status[port] = is_occupied
        return is_occupied, process_info
        
    def get_process_by_port(self, port):
        try:
            for conn in psutil.net_connections(kind='inet'):
                try:
                    if hasattr(conn, 'laddr') and conn.laddr and conn.laddr.port == port:
                        if conn.status == 'LISTEN':
                            try:
                                if conn.pid and conn.pid > 0:
                                    process = psutil.Process(conn.pid)
                                    return {
                                        'pid': conn.pid,
                                        'name': process.name(),
                                        'exe': process.exe() if process.exe() else 'Unknown',
                                        'cmdline': ' '.join(process.cmdline()) if process.cmdline() else 'Unknown'
                                    }
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                return {
                                    'pid': conn.pid,
                                    'name': 'Unknown',
                                    'exe': 'Unknown',
                                    'cmdline': 'Unknown'
                                }
                except (AttributeError, TypeError):
                    continue
                    
            result = subprocess.run(
                f'netstat -ano | findstr :{port} | findstr LISTENING',
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result.stdout:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid_str = parts[-1]
                        if pid_str.isdigit():
                            pid = int(pid_str)
                            try:
                                process = psutil.Process(pid)
                                return {
                                    'pid': pid,
                                    'name': process.name(),
                                    'exe': process.exe() if process.exe() else 'Unknown',
                                    'cmdline': ' '.join(process.cmdline()) if process.cmdline() else 'Unknown'
                                }
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                return {
                                    'pid': pid,
                                    'name': 'Unknown',
                                    'exe': 'Unknown',
                                    'cmdline': 'Unknown'
                                }
                                
        except Exception as e:
            self.logger.error(f"获取端口 {port} 进程信息时出错: {str(e)}")
            
        return None
        
    def execute_restart_script(self, port, process_info):
        """执行重启脚本 - 修复版本"""
        script_path = self.monitored_ports.get(port)
        
        if not script_path:
            self.log_message(f"[错误] 端口 {port} 未关联脚本")
            return False
            
        if not os.path.exists(script_path):
            self.log_message(f"[错误] 脚本文件不存在: {script_path}")
            return False
            
        try:
            script_dir = os.path.dirname(script_path)
            script_name = os.path.basename(script_path)
            script_abs_path = os.path.abspath(script_path)
            
            # 构建命令
            if script_name.endswith('.py'):
                cmd = f'"{sys.executable}" "{script_abs_path}" {port} {process_info["pid"]} "{process_info["name"]}"'
            elif script_name.endswith('.bat'):
                cmd = f'"{script_abs_path}" {port} {process_info["pid"]} "{process_info["name"]}"'
            elif script_name.endswith('.exe'):
                cmd = f'"{script_abs_path}" {port} {process_info["pid"]} "{process_info["name"]}"'
            else:
                self.log_message(f"[错误] 不支持的脚本类型: {script_name}")
                return False
                
            self.log_message(f"[执行] {script_name}")
            self.log_message(f"[命令] {cmd}")
            
            # 执行脚本
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags = subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # 使用 run 方法并设置编码
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=script_dir,
                startupinfo=startupinfo,
                encoding='utf-8',
                errors='replace'
            )
            
            # 记录脚本执行日志
            self.log_script_execution(port, cmd, result.stdout, result.stderr, result.returncode == 0)
            
            # 显示输出
            if result.stdout:
                self.log_message(f"[输出] {result.stdout[:500]}")
            if result.stderr:
                self.log_message(f"[错误输出] {result.stderr[:500]}")
            
            if result.returncode == 0:
                # 更新统计信息
                self.restart_total += 1
                self.restart_today += 1
                
                if port not in self.port_stats:
                    self.port_stats[port] = {'restart_count': 0, 'last_restart': None}
                self.port_stats[port]['restart_count'] += 1
                self.port_stats[port]['last_restart'] = datetime.now()
                
                self.update_port_tree()
                self.update_stats()
                
                self.log_message(f"[成功] 端口 {port} 的重启脚本执行成功")
                return True
            else:
                self.log_message(f"[失败] 脚本执行失败 (返回码: {result.returncode})")
                return False
                
        except subprocess.TimeoutExpired:
            error_msg = "脚本执行超时 (60秒)"
            self.log_message(f"[错误] {error_msg}")
            self.log_script_execution(port, cmd if 'cmd' in locals() else "Unknown", "", error_msg, False)
            return False
        except Exception as e:
            error_msg = f"执行脚本时出错: {str(e)}"
            self.log_message(f"[错误] {error_msg}")
            self.log_script_execution(port, cmd if 'cmd' in locals() else "Unknown", "", error_msg, False)
            return False
            
    def handle_port_idle(self, port):
        """处理端口空闲的情况"""
        self.log_message(f"[处理] 端口 {port} 空闲，开始处理...")
        
        if port not in self.port_retry_info:
            self.port_retry_info[port] = {
                'fail_count': 0,
                'last_fail_time': None,
                'is_disabled': False
            }
        
        retry_info = self.port_retry_info[port]
        
        if retry_info.get('is_disabled', False):
            self.log_message(f"[跳过] 端口 {port} 已被禁用，停止监控")
            return
        
        current_fail_count = retry_info.get('fail_count', 0)
        
        if current_fail_count >= self.max_retry_count:
            retry_info['is_disabled'] = True
            self.log_message(f"[禁用] 端口 {port} 重启失败次数已达上限 ({self.max_retry_count}次)，已停止监控该端口")
            self.log_message(f"[建议] 请手动恢复服务后，点击'重置失败计数'按钮恢复监控")
            self.update_port_tree()
            self.update_disabled_ports_display()
            return
        
        new_fail_count = current_fail_count + 1
        retry_info['fail_count'] = new_fail_count
        retry_info['last_fail_time'] = datetime.now()
        
        self.log_message(f"[重试 {new_fail_count}/{self.max_retry_count}] 执行重启脚本...")
        
        success = self.execute_restart_script(port, {'pid': 0, 'name': 'Unknown'})
        
        if success:
            self.log_message(f"[成功] 脚本执行成功，等待 {self.retry_interval} 秒验证服务...")
            time.sleep(self.retry_interval)
            
            new_process = self.get_process_by_port(port)
            if new_process:
                self.log_message(f"[验证] 端口 {port} 已恢复！进程: {new_process['name']} (PID: {new_process['pid']}) ✓")
                self.port_status[port] = True
                retry_info['fail_count'] = 0
                retry_info['is_disabled'] = False
                self.update_port_tree()
                self.update_port_status_display()
            else:
                self.log_message(f"[验证] 端口 {port} 尚未恢复，将在下次检查中继续重试")
        else:
            self.log_message(f"[失败] 脚本执行失败，失败次数: {new_fail_count}/{self.max_retry_count}")
            
        self.update_port_tree()
        self.update_stats()
        
    def monitor_ports(self):
        self.log_message("=" * 50)
        self.log_message("端口监控服务已启动")
        self.log_message(f"监控频率: {self.monitor_interval} 秒")
        self.log_message(f"最大重试次数: {self.max_retry_count}")
        self.log_message(f"重试间隔: {self.retry_interval} 秒")
        self.log_message(f"监控端口: {', '.join(map(str, self.monitored_ports.keys()))}")
        self.log_message("=" * 50)
        
        for port in self.monitored_ports.keys():
            process_info = self.get_process_by_port(port)
            is_occupied = process_info is not None
            self.port_status[port] = is_occupied
            
            if is_occupied:
                self.log_message(f"初始状态: 端口 {port} 已被 {process_info['name']} (PID: {process_info['pid']}) 占用 ✓")
                if port in self.port_retry_info:
                    self.port_retry_info[port]['fail_count'] = 0
                    self.port_retry_info[port]['is_disabled'] = False
            else:
                self.log_message(f"初始状态: 端口 {port} 空闲（无进程占用）⚠")
                self.log_message(f"[触发] 立即执行端口 {port} 的重启脚本...")
                self.handle_port_idle(port)
        
        self.update_port_tree()
        self.update_port_status_display()
        
        while self.monitoring:
            try:
                current_day = datetime.now().day
                if current_day != self.last_reset_day:
                    self.restart_today = 0
                    self.last_reset_day = current_day
                    self.update_stats()
                
                for port in list(self.monitored_ports.keys()):
                    if not self.monitoring:
                        break
                    
                    retry_info = self.port_retry_info.get(port, {})
                    if retry_info.get('is_disabled', False):
                        continue
                    
                    process_info = self.get_process_by_port(port)
                    is_occupied = process_info is not None
                    was_occupied = self.port_status.get(port, False)
                    
                    self.port_status[port] = is_occupied
                    
                    if is_occupied != was_occupied:
                        if is_occupied:
                            self.log_message(f"[恢复] 端口 {port} 已被 {process_info['name']} (PID: {process_info['pid']}) 占用 ✓")
                            if port in self.port_retry_info:
                                self.port_retry_info[port]['fail_count'] = 0
                                self.port_retry_info[port]['is_disabled'] = False
                            self.update_port_tree()
                            self.update_port_status_display()
                        else:
                            self.log_message(f"[警告] 端口 {port} 空闲！无进程占用该端口 ⚠")
                            self.handle_port_idle(port)
                    else:
                        if not is_occupied and not retry_info.get('is_disabled', False):
                            last_fail_time = retry_info.get('last_fail_time')
                            if last_fail_time:
                                elapsed = (datetime.now() - last_fail_time).total_seconds()
                                if elapsed >= self.retry_interval:
                                    self.log_message(f"[重试检查] 端口 {port} 仍为空闲（已等待{int(elapsed)}秒），继续重试...")
                                    self.handle_port_idle(port)
                
                time.sleep(self.monitor_interval)
                
            except Exception as e:
                self.logger.error(f"监控过程中出错: {str(e)}")
                import traceback
                self.logger.error(traceback.format_exc())
                time.sleep(self.monitor_interval)
                
        self.log_message("端口监控服务已停止")
        
    def update_port_tree(self):
        for item in self.port_tree.get_children():
            self.port_tree.delete(item)
            
        for port, script in self.monitored_ports.items():
            script_name = os.path.basename(script)
            stats = self.port_stats.get(port, {'restart_count': 0, 'last_restart': None})
            
            last_restart_value = stats.get('last_restart')
            if last_restart_value and isinstance(last_restart_value, datetime):
                last_restart = last_restart_value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                last_restart = "无"
                
            restart_count = stats.get('restart_count', 0)
            
            is_occupied = self.port_status.get(port, False)
            is_disabled = self.port_retry_info.get(port, {}).get('is_disabled', False)
            
            if is_disabled:
                status = "⚠ 已禁用"
            else:
                status = "✓ 正常" if is_occupied else "✗ 空闲"
            
            fail_count = self.port_retry_info.get(port, {}).get('fail_count', 0)
            
            item_id = self.port_tree.insert('', 'end', values=(port, script_name, status, fail_count, last_restart, restart_count))
            
            if is_disabled:
                self.port_tree.tag_configure('disabled', background='#FFE6E6')
                self.port_tree.item(item_id, tags=('disabled',))
            
        self.update_stats()
        self.update_disabled_ports_display()
        
    def update_port_status_display(self):
        if not self.monitored_ports:
            self.port_status_label.config(text="端口占用状态: 无监控端口", foreground="gray")
            return
            
        occupied_count = sum(1 for p in self.monitored_ports.keys() if self.port_status.get(p, False))
        total_count = len(self.monitored_ports)
        
        if occupied_count == total_count:
            status_text = f"端口占用状态: 全部正常 ({occupied_count}/{total_count})"
            color = "green"
        elif occupied_count == 0:
            status_text = f"端口占用状态: 全部空闲 ({occupied_count}/{total_count})"
            color = "red"
        else:
            status_text = f"端口占用状态: {occupied_count}/{total_count} 正常"
            color = "orange"
            
        self.port_status_label.config(text=status_text, foreground=color)
        
    def update_disabled_ports_display(self):
        if not hasattr(self, 'disabled_label'):
            return
            
        disabled_ports = [str(p) for p in self.monitored_ports.keys() 
                         if self.port_retry_info.get(p, {}).get('is_disabled', False)]
        
        if disabled_ports:
            ports_text = ", ".join(disabled_ports)
            self.disabled_label.config(text=f"已禁用端口: {ports_text}", foreground="red")
        else:
            self.disabled_label.config(text="已禁用端口: 无", foreground="gray")
        
    def update_stats(self):
        port_count = len(self.monitored_ports)
        total_failures = sum(info.get('fail_count', 0) for info in self.port_retry_info.values())
        
        if hasattr(self, 'stats_label'):
            self.stats_label.config(text=f"统计: 监控{port_count}个端口 | 今日重启{self.restart_today}次 | 总重启{self.restart_total}次 | 总失败{total_failures}次")
        
    def batch_import(self):
        file_path = filedialog.askopenfilename(
            title="批量导入配置文件",
            filetypes=[("CSV文件", "*.csv"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        
        if file_path:
            try:
                imported_count = 0
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if line and not line.startswith('#'):
                            parts = line.split(',')
                            if len(parts) >= 2:
                                port = int(parts[0].strip())
                                script = parts[1].strip()
                                if os.path.exists(script):
                                    self.monitored_ports[port] = script
                                    if port not in self.port_stats:
                                        self.port_stats[port] = {'restart_count': 0, 'last_restart': None}
                                    if port not in self.port_retry_info:
                                        self.port_retry_info[port] = {'fail_count': 0, 'last_fail_time': None, 'is_disabled': False}
                                    if port not in self.port_status:
                                        self.port_status[port] = False
                                    imported_count += 1
                                    self.log_message(f"导入端口配置: {port} -> {os.path.basename(script)}")
                                else:
                                    self.log_message(f"警告: 第{line_num}行脚本不存在: {script}")
                                    
                self.update_port_tree()
                self.save_config()
                messagebox.showinfo("成功", f"批量导入完成，共导入{imported_count}个端口配置")
                self.scan_ports_now()
                
            except Exception as e:
                messagebox.showerror("错误", f"导入失败: {str(e)}")
                
    def export_config(self):
        file_path = filedialog.asksaveasfilename(
            title="导出配置",
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")]
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("# 端口,脚本路径\n")
                    for port, script in self.monitored_ports.items():
                        f.write(f"{port},{script}\n")
                        
                messagebox.showinfo("成功", f"配置已导出到: {file_path}")
                
            except Exception as e:
                messagebox.showerror("错误", f"导出失败: {str(e)}")
                
    def apply_interval(self):
        try:
            new_interval = int(self.interval_var.get())
            if new_interval < 1 or new_interval > 60:
                raise ValueError
            self.monitor_interval = new_interval
            self.save_config()
            self.log_message(f"监控频率已更新为 {self.monitor_interval} 秒")
            messagebox.showinfo("成功", f"监控频率已更新为 {self.monitor_interval} 秒")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的秒数（1-60）")
            
    def apply_retry_settings(self):
        try:
            new_max_retry = int(self.max_retry_var.get())
            new_retry_interval = int(self.retry_interval_var.get())
            
            if new_max_retry < 1 or new_max_retry > 10:
                raise ValueError("最大重试次数必须在1-10之间")
            if new_retry_interval < 5 or new_retry_interval > 300:
                raise ValueError("重试间隔必须在5-300秒之间")
                
            self.max_retry_count = new_max_retry
            self.retry_interval = new_retry_interval
            self.save_config()
            self.log_message(f"重试设置已更新: 最大重试次数={self.max_retry_count}, 重试间隔={self.retry_interval}秒")
            messagebox.showinfo("成功", f"重试设置已更新")
        except ValueError as e:
            messagebox.showerror("错误", str(e))
            
    def apply_log_settings(self):
        try:
            new_keep_days = int(self.log_keep_days_var.get())
            if new_keep_days < 1 or new_keep_days > 365:
                raise ValueError
            self.log_keep_days = new_keep_days
            self.save_config()
            
            for handler in self.logger.handlers[:]:
                if isinstance(handler, TimedRotatingFileHandler):
                    handler.close()
                    self.logger.removeHandler(handler)
                    
            self.setup_logging()
            self.clean_old_logs()
            
            self.log_message(f"日志保存天数已更新为 {self.log_keep_days} 天")
            messagebox.showinfo("成功", f"日志保存天数已更新为 {self.log_keep_days} 天")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的天数（1-365）")
            
    def clean_old_logs(self):
        try:
            log_dir = "logs"
            if not os.path.exists(log_dir):
                return
                
            cutoff_date = datetime.now() - timedelta(days=self.log_keep_days)
            deleted_count = 0
            
            for filename in os.listdir(log_dir):
                file_path = os.path.join(log_dir, filename)
                if os.path.isfile(file_path):
                    mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if mtime < cutoff_date:
                        os.remove(file_path)
                        deleted_count += 1
                        
            if deleted_count > 0:
                self.log_message(f"清理了 {deleted_count} 个旧日志文件（超过{self.log_keep_days}天）")
                
        except Exception as e:
            self.log_message(f"清理旧日志时出错: {str(e)}")
            
    def schedule_log_cleanup(self):
        def cleanup_task():
            while True:
                time.sleep(86400)
                self.clean_old_logs()
                
        cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
        cleanup_thread.start()
        
    def refresh_log_files_list(self):
        self.log_files_listbox.delete(0, tk.END)
        log_dir = "logs"
        if os.path.exists(log_dir):
            if self.log_type_var.get() == "monitor":
                log_files = [f for f in os.listdir(log_dir) if f.startswith('port_monitor') and f.endswith('.log')]
            else:
                log_files = [f for f in os.listdir(log_dir) if f == 'script_execution.log']
            log_files.sort(reverse=True)
            for log_file in log_files:
                self.log_files_listbox.insert(tk.END, log_file)
                
    def view_selected_log(self):
        selection = self.log_files_listbox.curselection()
        if selection:
            log_file = self.log_files_listbox.get(selection[0])
            log_path = os.path.join("logs", log_file)
            
            self.log_content_text.delete(1.0, tk.END)
            
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    self.log_content_text.insert(1.0, content)
            except Exception as e:
                self.log_content_text.insert(1.0, f"读取日志文件失败: {str(e)}")
                
    def delete_selected_log(self):
        selection = self.log_files_listbox.curselection()
        if selection:
            log_file = self.log_files_listbox.get(selection[0])
            log_path = os.path.join("logs", log_file)
            
            if messagebox.askyesno("确认删除", f"确定要删除日志文件 {log_file} 吗？"):
                try:
                    os.remove(log_path)
                    self.refresh_log_files_list()
                    self.log_message(f"已删除日志文件: {log_file}")
                except Exception as e:
                    messagebox.showerror("错误", f"删除失败: {str(e)}")
                    
    def refresh_logs(self):
        self.refresh_log_files_list()
        
    def open_log_folder(self):
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        os.startfile(log_dir)
        
    def clear_log_display(self):
        self.log_text.delete(1.0, tk.END)
        
    def start_monitoring(self):
        if not self.monitoring:
            if not self.monitored_ports:
                messagebox.showwarning("警告", "请先添加要监控的端口")
                return
                
            self.log_message("正在启动监控服务...")
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self.monitor_ports, daemon=True)
            self.monitor_thread.start()
            self.monitor_status.set("监控运行中")
            self.start_stop_btn.config(text="停止监控")
            self.update_port_tree()
            self.log_message("✓ 监控服务已启动")
            
    def stop_monitoring(self):
        if self.monitoring:
            self.log_message("正在停止监控服务...")
            self.monitoring = False
            
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=2)
                
            self.monitor_status.set("监控已停止")
            self.start_stop_btn.config(text="启动监控")
            self.update_port_tree()
            self.log_message("✓ 监控服务已停止")
            
    def toggle_monitoring(self):
        if self.monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()
            
    def log_message(self, message):
        if hasattr(self, 'logger'):
            self.logger.info(message)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        if hasattr(self, 'log_text'):
            self.log_text.insert(tk.END, log_entry)
            self.log_text.see(tk.END)
            
            if int(self.log_text.index('end-1c').split('.')[0]) > 1000:
                self.log_text.delete(1.0, 500.0)
            
    def save_config(self):
        config = {
            'monitored_ports': self.monitored_ports,
            'monitor_interval': self.monitor_interval,
            'max_retry_count': self.max_retry_count,
            'retry_interval': self.retry_interval,
            'auto_start_monitor': self.auto_start_var.get() if hasattr(self, 'auto_start_var') else False,
            'log_keep_days': self.log_keep_days,
            'port_stats': self.port_stats,
            'restart_total': self.restart_total
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False, default=self.json_serialize)
        except Exception as e:
            self.log_message(f"保存配置失败: {str(e)}")
            
    def json_serialize(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)
            
    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.monitored_ports = {int(k): v for k, v in config.get('monitored_ports', {}).items()}
                    self.monitor_interval = config.get('monitor_interval', 5)
                    self.max_retry_count = config.get('max_retry_count', 3)
                    self.retry_interval = config.get('retry_interval', 30)
                    self.log_keep_days = config.get('log_keep_days', 30)
                    self.restart_total = config.get('restart_total', 0)
                    
                    port_stats_raw = config.get('port_stats', {})
                    for port, stats in port_stats_raw.items():
                        port_int = int(port)
                        last_restart = stats.get('last_restart')
                        if last_restart and isinstance(last_restart, str):
                            try:
                                last_restart = datetime.fromisoformat(last_restart)
                            except:
                                last_restart = None
                        self.port_stats[port_int] = {
                            'restart_count': stats.get('restart_count', 0),
                            'last_restart': last_restart
                        }
                    
                    for port in self.monitored_ports.keys():
                        if port not in self.port_status:
                            self.port_status[port] = False
                        if port not in self.port_retry_info:
                            self.port_retry_info[port] = {
                                'fail_count': 0,
                                'last_fail_time': None,
                                'is_disabled': False
                            }
                    
                    if hasattr(self, 'auto_start_var'):
                        self.auto_start_var.set(config.get('auto_start_monitor', False))
        except Exception as e:
            print(f"加载配置失败: {str(e)}")
            
    def on_closing(self):
        if self.monitoring:
            if messagebox.askokcancel("退出", "监控正在运行，确定要退出吗？"):
                self.monitoring = False
                time.sleep(1)
                self.save_config()
                self.root.destroy()
        else:
            self.save_config()
            self.root.destroy()

def main():
    root = tk.Tk()
    app = PortMonitor(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()