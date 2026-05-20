import sys, json, smtplib
from email.mime.text import MIMEText

def send(to, subject, body, smtp_host="smtp.qq.com", smtp_port=587, sender="", password=""):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject; msg["From"] = sender; msg["To"] = to
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls(); server.login(sender, password); server.sendmail(sender, [to], msg.as_string())
    return "邮件已发送"

if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(send(**args))