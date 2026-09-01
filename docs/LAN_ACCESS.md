# Private LAN access

Webnovel publishes only its frontend to the private LAN. Phone, tablet, and laptop browsers connect to the detected host IPv4 address and the frontend port. Nginx then proxies same-origin `/api`, SEO pages, and forms to the backend over the dedicated Docker network.

```text
phone or tablet -> http://PC-LAN-IP:5273 -> frontend Nginx -> backend:8270
```

PostgreSQL (`55432`), Redis (`56379`), the direct backend (`8270`), and optional MinIO ports remain bound to `127.0.0.1`. No router port forwarding or public Internet exposure is configured.

## One-time Windows Firewall setup

From an Administrator PowerShell in `C:\Users\anadh\Development\Webnovel` run:

```powershell
.\scripts\configure-lan-firewall.ps1
```

The idempotent rule is named `Webnovel LAN TCP 5273 (Private)` and allows inbound TCP 5273 only while Windows identifies the network as Private. Windows Firewall remains enabled. If startup selects a different frontend port, run the script with that exact port:

```powershell
.\scripts\configure-lan-firewall.ps1 -Port 5274
```

## Start and connect

Run `scripts\start.ps1`. It ignores virtual, Docker, WSL, VPN, loopback, and link-local adapters where possible, prefers a physical Ethernet or Wi-Fi address with a default gateway, verifies both localhost and LAN health, and prints the exact phone/tablet URL.

Both devices must be connected to the same LAN. On Eero and similar routers, a guest network or client-isolation option may intentionally block LAN clients from reaching each other. That is an external router condition; Webnovel does not change router settings or enable port forwarding.
