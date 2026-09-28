#!/bin/bash
# vpn-e2: WireGuard on OCI E2.1.Micro (Ubuntu 22.04). Client configs are printed ONLY to the serial console.
exec > >(tee -a /var/log/wg-setup.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y wireguard qrencode curl iptables-persistent
PORT=51820
iptables -I INPUT 1 -p udp --dport $PORT -j ACCEPT
iptables -I FORWARD 1 -i wg0 -j ACCEPT
iptables -I FORWARD 1 -o wg0 -j ACCEPT
netfilter-persistent save
echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-wg.conf
sysctl --system
IF=$(ip route show default | awk '{print $5; exit}')
PUB=$(curl -s --max-time 10 https://ifconfig.me || curl -s --max-time 10 https://api.ipify.org)
cd /etc/wireguard && umask 077
wg genkey | tee server.key | wg pubkey > server.pub
cat > wg0.conf <<CONF
[Interface]
Address = 10.8.0.1/24
ListenPort = $PORT
PrivateKey = $(cat server.key)
PostUp = iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o $IF -j MASQUERADE
PostDown = iptables -t nat -D POSTROUTING -s 10.8.0.0/24 -o $IF -j MASQUERADE
CONF
OUT=""
i=2
for name in iphone computer spare; do
  wg genkey | tee $name.key | wg pubkey > $name.pub
  printf '\n[Peer]\n# %s\nPublicKey = %s\nAllowedIPs = 10.8.0.%s/32\n' "$name" "$(cat $name.pub)" "$i" >> wg0.conf
  cat > $name.conf <<CONF
[Interface]
PrivateKey = $(cat $name.key)
Address = 10.8.0.$i/32
DNS = 1.1.1.1, 8.8.8.8
MTU = 1380

[Peer]
PublicKey = $(cat server.pub)
Endpoint = $PUB:$PORT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
CONF
  i=$((i+1))
done
systemctl enable --now wg-quick@wg0
for c in /dev/ttyS0 /dev/console; do
  { echo "=====WG-BEGIN====="; for name in iphone computer spare; do echo "---$name---"; cat /etc/wireguard/$name.conf; done; echo "=====WG-END====="; } > $c 2>/dev/null
done
