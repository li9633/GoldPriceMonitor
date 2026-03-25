# notifier.py
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from config import EMAIL_CONFIG, SYMBOL_NAME_MAP


class Notifier:
    def __init__(self):
        self.config = EMAIL_CONFIG

    def send_email_alert(self, symbol: str, current_price: float, alert_messages: list[str]):
        """发送邮件报警"""
        subject = f"黄金价格监控报警 - {SYMBOL_NAME_MAP.get(symbol, symbol)} - {current_price}"

        body = "\n\n".join(alert_messages)
        body += f"\n\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        body += f"\n监控品种: {SYMBOL_NAME_MAP.get(symbol, symbol)} ({symbol})"

        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = self.config['sender_email']
        msg['To'] = self.config['receiver_email']

        try:
            server = smtplib.SMTP(
                self.config['smtp_server'], self.config['smtp_port'])
            server.starttls()
            server.login(self.config['sender_email'],
                         self.config['sender_password'])
            server.send_message(msg)
            server.quit()
            print(f"[{datetime.now()}] 邮件发送成功: {subject}")
            return True
        except Exception as e:
            print(f"[{datetime.now()}] 邮件发送失败: {e}")
            return False

    # 可在此添加其他通知方式，如微信机器人、短信等
    # def send_wechat_alert(self, message):
    #     pass
