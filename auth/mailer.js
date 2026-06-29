const nodemailer = require('nodemailer');

const transporter = nodemailer.createTransport({
  host: 'smtp.qq.com',
  port: 465,
  secure: true,
  auth: {
    user: process.env.QQ_MAIL_USER,
    pass: process.env.QQ_MAIL_PASS
  }
});

async function sendVerifyCode(toEmail, code) {
  await transporter.sendMail({
    from: `"润墨智检" <${process.env.QQ_MAIL_USER}>`,
    to: toEmail,
    subject: '【润墨智检】您的验证码',
    html: `
      <div style="font-family:'PingFang SC','Microsoft YaHei',sans-serif;max-width:480px;margin:0 auto;background:#f8fafc;padding:32px;border-radius:12px;">
        <h2 style="margin:0 0 8px;color:#1e293b;font-size:20px;">润墨智检</h2>
        <p style="color:#64748b;margin:0 0 24px;font-size:13px;">您好，以下是您的注册验证码：</p>
        <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:24px;text-align:center;">
          <div style="font-size:36px;font-weight:700;letter-spacing:10px;color:#6366f1;">${code}</div>
        </div>
        <p style="color:#94a3b8;font-size:12px;margin:20px 0 0;">验证码 <strong>5 分钟</strong>内有效，请勿泄露给他人。</p>
        <p style="color:#cbd5e1;font-size:11px;margin:6px 0 0;">如非本人操作，请忽略此邮件。</p>
      </div>
    `
  });
}

async function sendVerificationEmail(toEmail, verifyLink) {
  await transporter.sendMail({
    from: `"润墨智检" <${process.env.QQ_MAIL_USER}>`,
    to: toEmail,
    subject: '【润墨智检】请验证您的邮箱',
    html: `
      <div style="font-family:'PingFang SC','Microsoft YaHei',sans-serif;max-width:480px;margin:0 auto;background:#f8fafc;padding:32px;border-radius:12px;">
        <h2 style="margin:0 0 8px;color:#1e293b;font-size:20px;">润墨智检</h2>
        <p style="color:#64748b;margin:0 0 24px;font-size:13px;">感谢注册！请点击下方按钮验证您的邮箱，完成注册。</p>
        <div style="text-align:center;margin:24px 0;">
          <a href="${verifyLink}" style="display:inline-block;background:#6366f1;color:#fff;text-decoration:none;padding:13px 36px;border-radius:8px;font-size:15px;font-weight:600;">验证邮箱</a>
        </div>
        <p style="color:#94a3b8;font-size:12px;margin:16px 0 0;">链接 <strong>24 小时</strong>内有效。若无法点击，请复制以下链接到浏览器：</p>
        <p style="color:#6366f1;font-size:11px;word-break:break-all;margin:6px 0 0;">${verifyLink}</p>
        <p style="color:#cbd5e1;font-size:11px;margin:12px 0 0;">如非本人操作，请忽略此邮件。</p>
      </div>
    `
  });
}

async function sendPasswordResetEmail(toEmail, resetLink) {
  await transporter.sendMail({
    from: `"润墨智检" <${process.env.QQ_MAIL_USER}>`,
    to: toEmail,
    subject: '【润墨智检】密码重置',
    html: `
      <div style="font-family:'PingFang SC','Microsoft YaHei',sans-serif;max-width:480px;margin:0 auto;background:#f8fafc;padding:32px;border-radius:12px;">
        <h2 style="margin:0 0 8px;color:#1e293b;font-size:20px;">润墨智检</h2>
        <p style="color:#64748b;margin:0 0 24px;font-size:13px;">您申请了密码重置，请点击下方按钮设置新密码。</p>
        <div style="text-align:center;margin:24px 0;">
          <a href="${resetLink}" style="display:inline-block;background:#6366f1;color:#fff;text-decoration:none;padding:13px 36px;border-radius:8px;font-size:15px;font-weight:600;">重置密码</a>
        </div>
        <p style="color:#94a3b8;font-size:12px;margin:16px 0 0;">链接 <strong>30 分钟</strong>内有效。若无法点击，请复制以下链接到浏览器：</p>
        <p style="color:#6366f1;font-size:11px;word-break:break-all;margin:6px 0 0;">${resetLink}</p>
        <p style="color:#cbd5e1;font-size:11px;margin:12px 0 0;">如非本人操作，请忽略此邮件，您的密码不会被更改。</p>
      </div>
    `
  });
}

module.exports = { sendVerifyCode, sendVerificationEmail, sendPasswordResetEmail };
