# project

## grab-a1：OCI 免费 ARM 自动抢机

GitHub Actions 每 5 分钟尝试在 Oracle Cloud（us-sanjose-1）创建一台 `VM.Standard.A1.Flex`（4 OCPU / 24 GB，Ubuntu 22.04，50 GB 启动盘）。
抢到后自动停用 workflow；账户里已有 A1 实例时也会直接收工。

需要的 Secrets（Settings → Secrets and variables → Actions）：

| 名称 | 内容 |
|---|---|
| `OCI_USER_OCID` | 用户 OCID |
| `OCI_TENANCY_OCID` | 租户 OCID |
| `OCI_FINGERPRINT` | API Key 指纹 |
| `OCI_PRIVATE_KEY` | API 私钥 .pem 全文 |
| `SSH_PUBLIC_KEY` | 登录新机器用的 SSH 公钥 |
| `OCI_SUBNET_ID` | 可选，不填则自动选第一个公网子网 |
