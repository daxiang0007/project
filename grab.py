"""OCI 免费 ARM (VM.Standard.A1.Flex) 自动抢机脚本 —— 由 GitHub Actions 定时调用。"""
import os
import re
import sys
import time

import oci

SHAPE = "VM.Standard.A1.Flex"
REQUIRED = ["OCI_USER_OCID", "OCI_TENANCY_OCID", "OCI_FINGERPRINT", "OCI_PRIVATE_KEY", "SSH_PUBLIC_KEY"]

OCPUS = float(os.environ.get("TARGET_OCPUS") or 4)
MEM_GB = float(os.environ.get("TARGET_MEMORY_GB") or OCPUS * 6)
BOOT_GB = int(os.environ.get("BOOT_VOLUME_GB") or 50)
OS_VERSION = os.environ.get("UBUNTU_VERSION") or "22.04"
ATTEMPTS = int(os.environ.get("ATTEMPTS") or 4)
INTERVAL = int(os.environ.get("INTERVAL_SECONDS") or 60)
NAME = os.environ.get("INSTANCE_NAME") or "a1-free"


def set_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def main():
    missing = [k for k in REQUIRED if not os.environ.get(k, "").strip()]
    if missing:
        print(f"::warning::Secrets 未配置完整，本轮跳过：{', '.join(missing)}")
        return

    def ocid(name, kind):
        m = re.search(rf"ocid1\.{kind}\.[a-z0-9.\-]*\.[a-z0-9]+", os.environ[name])
        if not m:
            sys.exit(f"{name} 里找不到 ocid1.{kind}... 格式的 OCID，请在 OCI 控制台点 Copy 重新复制")
        return m.group(0)

    tenancy = ocid("OCI_TENANCY_OCID", "tenancy")
    fp_m = re.search(r"(?<![0-9a-f])(?:[0-9a-f]{2}:){15}[0-9a-f]{2}(?![0-9a-f])", os.environ["OCI_FINGERPRINT"].lower())
    if not fp_m:
        sys.exit("OCI_FINGERPRINT 里找不到 xx:xx:...（16 组）格式的指纹，请去 OCI API keys 列表重新复制")
    fp = fp_m.group(0)
    key = os.environ["OCI_PRIVATE_KEY"].strip()
    m = re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", key, re.S)
    if not m:
        sys.exit("OCI_PRIVATE_KEY 里找不到 BEGIN/END PRIVATE KEY，请粘贴 .pem 全文")
    key = m.group(0)
    cfg = {
        "user": ocid("OCI_USER_OCID", "user"),
        "tenancy": tenancy,
        "fingerprint": fp,
        "key_content": key + "\n",
        "region": (os.environ.get("OCI_REGION") or "us-sanjose-1").strip(),
    }
    oci.config.validate_config(cfg)
    ssh_parts = os.environ["SSH_PUBLIC_KEY"].split()
    if not ssh_parts or not ssh_parts[0].startswith(("ssh-", "ecdsa-")):
        sys.exit("SSH_PUBLIC_KEY 不是公钥格式（应以 ssh-ed25519 / ssh-rsa 开头），是不是贴成私钥了？")
    print(f"SSH 公钥类型={ssh_parts[0]} 备注={ssh_parts[2] if len(ssh_parts) > 2 else '-'}")
    compute = oci.core.ComputeClient(cfg)
    network = oci.core.VirtualNetworkClient(cfg)
    identity = oci.identity.IdentityClient(cfg)

    # 1) 已经有 A1 实例就收工
    instances = oci.pagination.list_call_get_all_results(compute.list_instances, compartment_id=tenancy).data
    alive = [i for i in instances if i.shape == SHAPE and i.lifecycle_state not in ("TERMINATED", "TERMINATING")]
    if alive:
        print(f"已存在 A1 实例：{[(i.display_name, i.lifecycle_state) for i in alive]}，无需再抢。")
        set_output("done", "true")
        return

    # 2) 自动发现 AD / 镜像 / 子网
    ads = [a.name for a in identity.list_availability_domains(tenancy).data]
    images = compute.list_images(
        compartment_id=tenancy, operating_system="Canonical Ubuntu", operating_system_version=OS_VERSION,
        shape=SHAPE, sort_by="TIMECREATED", sort_order="DESC",
    ).data
    if not images:
        sys.exit(f"找不到 Ubuntu {OS_VERSION} ARM 镜像")
    image_id = images[0].id

    subnet_id = (os.environ.get("OCI_SUBNET_ID") or "").strip()
    if not subnet_id:
        subnets = [s for s in network.list_subnets(compartment_id=tenancy).data if s.lifecycle_state == "AVAILABLE"]
        subnets.sort(key=lambda s: s.prohibit_public_ip_on_vnic)  # 公网子网优先
        if not subnets:
            sys.exit("没有可用子网：请先在 OCI 控制台建一个 VCN（向导默认即可）")
        subnet_id = subnets[0].id
    print(f"AD={ads} image={images[0].display_name} subnet=...{subnet_id[-8:]} shape={OCPUS}C/{MEM_GB}G")

    details = lambda ad: oci.core.models.LaunchInstanceDetails(
        availability_domain=ad, compartment_id=tenancy, display_name=NAME, shape=SHAPE,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=OCPUS, memory_in_gbs=MEM_GB),
        source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=image_id, boot_volume_size_in_gbs=BOOT_GB),
        create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True),
        metadata={"ssh_authorized_keys": os.environ["SSH_PUBLIC_KEY"].strip()},
    )

    # 3) 抢
    for n in range(1, ATTEMPTS + 1):
        for ad in ads:
            try:
                inst = compute.launch_instance(details(ad)).data
                print(f"::notice::抢到了！{inst.display_name} {inst.id} ({ad})")
                set_output("done", "true")
                return
            except oci.exceptions.ServiceError as e:
                msg = f"{e.status} {e.code}: {e.message}"
                if e.status == 429 or "capacity" in (e.message or "").lower() or e.status >= 500:
                    print(f"[{n}/{ATTEMPTS}] {ad} 没货/限流 -> {msg}")
                else:
                    sys.exit(f"不可重试的错误（检查配额/参数/密钥）：{msg}")
        if n < ATTEMPTS:
            time.sleep(INTERVAL)
    print("本轮没抢到，等下一轮。")


if __name__ == "__main__":
    main()
