# PortMonitor

打包命令
pyinstaller --onefile --windowed --name=PortMonitor --uac-admin port_monitor.py

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
