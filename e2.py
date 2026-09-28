"""一次性：在 OCI 开一台永久免费 E2.1.Micro 跑 WireGuard（vpn-e2）。客户端配置只打到串口控制台，不进 Actions 日志。"""
import base64, os, re, sys, time
import oci

def pick(pattern, key, flags=0):
    m = re.search(pattern, os.environ.get(key, ""), flags)
    if not m:
        sys.exit(f"{key} 格式不对")
    return m.group(0)

tenancy = pick(r"ocid1\.tenancy\.[^\s\"']+", "OCI_TENANCY_OCID")
cfg = {
    "user": pick(r"ocid1\.user\.[^\s\"']+", "OCI_USER_OCID"),
    "tenancy": tenancy,
    "fingerprint": pick(r"([0-9a-fA-F]{2}:){15}[0-9a-fA-F]{2}", "OCI_FINGERPRINT").lower(),
    "key_content": pick(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "OCI_PRIVATE_KEY", re.S) + "\n",
    "region": "us-sanjose-1",
}
oci.config.validate_config(cfg)
compute = oci.core.ComputeClient(cfg)
network = oci.core.VirtualNetworkClient(cfg)
ident = oci.identity.IdentityClient(cfg)
SHAPE = "VM.Standard.E2.1.Micro"
NAME = "vpn-e2"

for inst in compute.list_instances(tenancy).data:
    if inst.display_name == NAME and inst.lifecycle_state not in ("TERMINATED", "TERMINATING"):
        sys.exit(f"已经有一台 {NAME}（{inst.lifecycle_state}），不重复创建")

ad = ident.list_availability_domains(tenancy).data[0].name
imgs = compute.list_images(tenancy, operating_system="Canonical Ubuntu", operating_system_version="22.04",
                           shape=SHAPE, sort_by="TIMECREATED", sort_order="DESC").data
imgs = [i for i in imgs if "Minimal" not in i.display_name] or imgs
if not imgs:
    sys.exit("找不到 Ubuntu 22.04 镜像")

subnet_id = os.environ.get("OCI_SUBNET_ID", "").strip()
if not subnet_id:
    subnets = [s for s in network.list_subnets(compartment_id=tenancy).data if s.lifecycle_state == "AVAILABLE"]
    subnets.sort(key=lambda s: s.prohibit_public_ip_on_vnic)
    subnet_id = subnets[0].id
subnet = network.get_subnet(subnet_id).data

# 确保子网安全列表放行 UDP 51820
for sl_id in subnet.security_list_ids:
    sl = network.get_security_list(sl_id).data
    ok = any(r.protocol == "17" and r.udp_options and r.udp_options.destination_port_range
             and r.udp_options.destination_port_range.min <= 51820 <= r.udp_options.destination_port_range.max
             for r in sl.ingress_security_rules)
    print(f"安全列表 {sl.display_name}: UDP 51820 {'已放行' if ok else '未放行'}")
    if not ok and sl_id == subnet.security_list_ids[0]:
        rules = list(sl.ingress_security_rules) + [oci.core.models.IngressSecurityRule(
            protocol="17", source="0.0.0.0/0", description="WireGuard",
            udp_options=oci.core.models.UdpOptions(destination_port_range=oci.core.models.PortRange(min=51820, max=51820)))]
        network.update_security_list(sl_id, oci.core.models.UpdateSecurityListDetails(ingress_security_rules=rules))
        print("已添加 UDP 51820 入站规则")

user_data = base64.b64encode(open("e2-cloud-init.sh", "rb").read()).decode()
details = oci.core.models.LaunchInstanceDetails(
    availability_domain=ad, compartment_id=tenancy, display_name=NAME, shape=SHAPE,
    source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=imgs[0].id, boot_volume_size_in_gbs=50),
    create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet_id, assign_public_ip=True),
    metadata={"ssh_authorized_keys": os.environ["SSH_PUBLIC_KEY"].strip(), "user_data": user_data},
)
print(f"AD={ad} image={imgs[0].display_name}")
inst = None
for n in range(1, 41):
    try:
        inst = compute.launch_instance(details).data
        break
    except oci.exceptions.ServiceError as e:
        print(f"[{n}] {e.status} {e.code}: {e.message}")
        if e.status == 429 or e.status >= 500 or "capacity" in (e.message or "").lower():
            time.sleep(45)
            continue
        sys.exit(1)
if not inst:
    sys.exit("E2 暂时没货，稍后再跑一次")
print(f"::notice::已创建 {NAME}，等待启动…")
inst = oci.wait_until(compute, compute.get_instance(inst.id), "lifecycle_state", "RUNNING", max_wait_seconds=900).data
vnic_id = compute.list_vnic_attachments(tenancy, instance_id=inst.id).data[0].vnic_id
ip = network.get_vnic(vnic_id).data.public_ip
print(f"::notice::{NAME} RUNNING，公网 IP {ip}（WireGuard 大约 3-5 分钟后装好）")
