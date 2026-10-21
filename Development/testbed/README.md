# WRW telemetry – dev testbed (SOM + CAM)

Mengikuti diagram: MQ-BRIDGE di SOM meneruskan data dari alat ke **dua** broker sekaligus. Broker SOM ada di mesin yang sama, broker CAM ada di seberang jaringan.

```
                                         ┌─▶ mqbroker-som ─▶ nodered-som ─▶ influx-som     (SOM)
Lunatico, Alcor ──pubdata/#──▶ mqbridge ─┤
 (simulator)        MQTT 5       +plugin └─▶ mqbroker-cam ─▶ nodered-cam ─▶ influx-cam     (CAM)
                                 timestamp      (topik di kedua broker: wrwo/som/pubdata/…)
```

Pendekatannya sama dengan repo WRW: Mosquitto bridge + plugin `mosquitto_message_timestamp` (sumber dari `MQTT Bridge/` di repo WRW). Plugin dikompilasi ulang di dalam image saat build.

## Menjalankan

```bash
docker compose up -d --build
docker compose logs -f mqbridge
```

| | SOM | CAM |
|---|---|---|
| Node-RED | http://localhost:1880 | http://localhost:1881 |
| InfluxDB (db `wrwo`) | localhost:8086 | localhost:8087 |
| Broker | localhost:1884 | localhost:1885 |
| Grafana | http://localhost:3000 | http://localhost:3001 |

Device connect ke **MQ-BRIDGE `localhost:1883`**, user `device`, password `DEVICE_PASS` dari `.env`.

## Menjalankan di Windows

Syarat: Docker Desktop dengan backend **WSL 2** dan mode **Linux containers**, dalam keadaan sudah jalan (ikon paus di tray tidak lagi "starting").

```powershell
cd C:\path\ke\wrw-testbed
copy .env.example .env      # sekali saja, lalu ganti password CHANGE_ME
docker compose up -d --build
docker compose ps
docker compose logs -f mqbridge
```

Skrip versi PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\outage.ps1 cam 60
powershell -ExecutionPolicy Bypass -File .\scripts\outage.ps1 bridge
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1 30m
```

Hal yang sering jadi masalah di Windows:

- **Line ending CRLF.** Container Linux butuh LF. Entrypoint sudah membuang `\r` otomatis, dan `.gitattributes` menjaga LF kalau folder ini dimasukkan ke git.
- **Port bentrok.** Mosquitto untuk Windows yang terpasang sebagai service akan memakai port 1883. Cek dengan `netstat -ano | findstr ":1883 :1880 :8086"`. Hyper-V juga kadang mencadangkan rentang port; cek dengan `netsh interface ipv4 show excludedportrange protocol=tcp`. Kalau bentrok, ganti port di `.env`.
- **Firewall.** Supaya alat di LAN bisa connect ke port 1883 di PC ini, izinkan Docker Desktop di jaringan *Private* saat Windows Firewall bertanya.
- **Jam WSL 2 bisa melenceng setelah laptop sleep atau hibernate.** Plugin memberi timestamp dari jam VM Docker, bukan langsung dari jam Windows.
  - Cek dengan `docker run --rm alpine date -u` lalu bandingkan dengan jam Windows.
  - Kalau selisih, jalankan `wsl --shutdown` lalu buka lagi Docker Desktop.
  - Untuk SOM produksi, lebih aman Linux atau Raspberry Pi dengan chrony/NTP.
- **Proxy kampus.** Kalau internet lewat proxy, isi proxy di Docker Desktop (Settings → Resources → Proxies). Build butuh akses ke Docker Hub, `dl-cdn.alpinelinux.org`, GitHub, dan PyPI.

## Simulasi gangguan

```bash
./scripts/outage.sh cam 60     # link SOM→CAM putus 60 detik (broker CAM dimatikan)
./scripts/outage.sh som 30     # broker SOM mati 30 detik
./scripts/outage.sh bridge     # restart MQ-BRIDGE
./scripts/check.sh 30m         # bandingkan jumlah titik dan delay di SOM vs CAM
```

Windows: lihat bagian *Menjalankan di Windows*.

Selama CAM putus, SOM tetap menerima data seperti biasa. Data untuk CAM diantrekan di MQ-BRIDGE dan dikirim begitu CAM kembali, dengan timestamp asli dari plugin. Field `delay_s` di CAM menunjukkan seberapa terlambat data itu tiba.

## Isi folder

| File | Fungsi |
|---|---|
| `mosquitto/Dockerfile.bridge` | eclipse-mosquitto 2.0.22 + plugin yang dikompilasi untuk image itu (Alpine/musl). `.so` dari repo WRW dibuat untuk Debian ARM64 dan tidak bisa dimuat di container. |
| `mosquitto/plugin/mosquitto_message_timestamp.c` | sumber plugin dari repo WRW (`MQTT Bridge/`). Menambahkan user property `timestamp` = Unix nanodetik. |
| `mosquitto/mqbridge.conf` | dua `connection`: `som-local` dan `som-to-cam` |
| `mosquitto/mqbroker.conf` | dipakai broker SOM dan CAM |
| `mosquitto/entrypoint.sh` | mengisi `${VAR}` di config dari env dan membuat password file dari `MQ_USERS` |
| `nodered/make_flows.py` | membuat `nodered/{som,cam}/data` (flow sama, env berbeda) |
| `grafana/` | provisioning datasource InfluxDB (URL dari env) dan dashboard `wrwo.json` + `wrwo-daily.json` (dibuat oleh `make_dashboard.py`), sama untuk SOM dan CAM |
| `portainer/` | Portainer CE (opsional), compose terpisah dari stack |
| `devices/alcor/` | Alcor Solar Seeing Monitor (USB) → MQTT: `alcor_ssm_mqtt.py`, service systemd, aturan udev |
| `simulator/` | data palsu, QoS 0: Lunatico AAG CloudWatcher (format JSON asli, tiap `SIM_CW_INTERVAL`=30 detik, dengan periode berawan dan hujan sesekali), Alcor seeing (payload sama dengan `alcor_ssm_mqtt.py`, tiap 2 detik, hanya siang hari), dan telegraf |

## Pengaturan penting di `mqbridge.conf`

- `max_queued_messages 0`: default-nya 1000. Lewat dari itu, pesan untuk CAM **dibuang** selama link putus. Batas `max_queued_bytes` (default 500 MB) menjaga RAM.
- `upgrade_outgoing_qos true`: device QoS 0 (telegraf, alat kecil) tetap ikut diantrekan.
- `bridge_protocol_version mqttv50` di kedua koneksi: tanpa ini user property `timestamp` hilang.
- Plugin **hanya** dipasang di MQ-BRIDGE, sehingga SOM dan CAM menerima timestamp yang persis sama.
- QoS 1, bukan 2 seperti di repo WRW. Pesan yang terkirim ulang tidak menggandakan data, karena di Influx titik dengan timestamp yang sama ditimpa.

## Node-RED

Flow: `mqtt in wrwo/+/pubdata/#` (MQTT 5) → **parse + timestamp + QC** → line protocol → `POST /write?precision=ns`.

- Timestamp diambil dari `msg.userProperties.timestamp`, berupa string nanodetik. Karena tetap string, presisinya tidak hilang di JavaScript.
- Kalau alat MQTT 5 mengirim user property `timestamp` sendiri, pesan membawa dua `timestamp`. Node-RED menggabungkannya menjadi string `'["<alat>","<plugin>"]'`, lalu parser mengambil angka terakhir, yaitu milik plugin. Jadi timestamp dari alat tidak pernah dipakai.
- Kalau property itu tidak ada (misalnya pesan tidak lewat bridge), dipakai waktu Node-RED dan diberi tag `ts_source=nodered`.
- Payload yang dikenali: JSON, JSON telegraf (`name`/`fields`/`tags`), angka, `k=v,k=v`, atau teks biasa (disimpan sebagai `raw`).
- Batas QC (`LIMITS`) dan offset kalibrasi (`OFFSET`) ada di function node tersebut.
- Database dibuat otomatis saat start (`CREATE DATABASE`).
- Login MQTT diambil dari env lewat `flows_cred.json` (`credentialSecret: false`). Ini hanya untuk dev. Untuk produksi, isi `credentialSecret` dan aktifkan `adminAuth`.

## Grafana

Grafana ada di SOM (`grafana-som`, port 3000) dan CAM (`grafana-cam`, port 3001). Masing-masing membaca InfluxDB di mesinnya sendiri. Datasource dan dashboard **WRW telemetry** dipasang otomatis dari `grafana/`, dan dashboard itu langsung jadi halaman utama.

- Tanpa login, dashboard bisa dilihat sebagai Viewer (khusus dev). Untuk mengedit, login sebagai `admin` dengan password `GRAFANA_ADMIN_PASS` dari `.env`. Password ini hanya dipakai saat Grafana start pertama kali. Kalau diganti setelahnya, pakai `docker compose exec grafana-som grafana cli admin reset-admin-password <baru>`.
- Dashboard berbahasa Inggris dan isinya:
  - **Pipeline**: points per minute (batang 0 berarti ada celah data), `delay_s` yang melonjak setelah link putus, nilai yang ditolak QC, dan jumlah titik tanpa timestamp plugin (harus 0).
  - **Lunatico AAG CloudWatcher**:
    - status SAFE/UNSAFE;
    - nilai terakhir clouds, temperature, humidity, wind, dan rain sensor;
    - timeline *safety conditions*;
    - grafik suhu/titik embun/IR mentah, clouds, kelembapan, angin, hujan, dan cahaya.
  - **Alcor Solar Seeing Monitor**:
    - seeing (biru < 1″, hijau < 2″, kuning < 3″, merah ≥ 3″, sesuai kelas manufaktur);
    - r₀, suhu box, dan status *valid seeing*;
    - grafik seeing, r₀, sinyal matahari, dan suhu box.
  - **Telegraf**: CPU idle.
- Dashboard dibuat oleh `grafana/make_dashboard.py`. Untuk mengubahnya, edit skrip itu lalu jalankan `python3 grafana/make_dashboard.py`, dan salin `grafana/dashboards/*.json` ke kedua mesin. Grafana membaca ulang file tersebut dalam 30 detik. Perubahan dari UI tidak bisa disimpan di atas file; pakai **Save as** untuk menyimpan salinan di Grafana.

### Statistik harian

Dashboard kedua, **WRW daily statistics**, bisa dibuka lewat link *Daily statistics* di kanan atas dashboard utama. Isinya:
- tabel per hari: jumlah titik dan delay terburuk per alat (bandingkan SOM vs CAM), CloudWatcher (suhu, kelembapan, awan, angin, hujan, % waktu aman), dan Alcor seeing (min/mean/max, r₀, suhu box, % sampel valid);
- grafik tren harian;
- tabel **semua field**, yaitu min/mean/max setiap nilai numerik.

Sumber datanya adalah *continuous query* `daily_stats` di InfluxDB:
- Node-RED membuatnya otomatis setiap start, di SOM dan CAM.
- CQ ini menghitung `mean_*`, `min_*`, `max_*` untuk **semua field numerik di semua measurement** (alat baru otomatis ikut), plus `points`, per hari lokal (zona waktu `TZ`, 00:00 WIB).
- Hasilnya disimpan di retention policy `daily` yang disimpan selamanya, jadi tetap ada walaupun data mentah nanti dibatasi umurnya.
- Data hari ini dan kemarin dihitung ulang setiap jam, jadi data yang telat masuk setelah outage tetap terhitung. Baris hari ini selalu parsial.
- Field teks (`cloudsSafe`, `quality`, …) dilewati. `mean_safe` dan `mean_valid_seeing` memberi persentase waktu.

Query manual, contohnya:
```bash
docker compose exec influx-som influx -database wrwo -execute 'SELECT * FROM wrwo.daily.seeing'
```

Saat start, Node-RED hanya mengisi 2 hari terakhir. Untuk menghitung **riwayat yang lebih lama** (misalnya data sebelum fitur ini dipasang), jalankan sekali di tiap mesin. Ganti `influx-som` dengan `influx-cam` di CAM, dan `400d` sesuai kebutuhan:
```bash
docker compose exec influx-som influx -database wrwo -execute "SELECT mean(*), min(*), max(*), count(\"delay_s\") AS points INTO \"wrwo\".\"daily\".:MEASUREMENT FROM \"wrwo\".\"autogen\"./.*/ WHERE time > now() - 400d GROUP BY time(1d), \"site\", \"device\" tz('Asia/Jakarta')"
```

## Memisah ke mesin sungguhan

Service dibagi ke dua file:
- `compose.som.yml`: mqbridge, mqbroker-som, nodered-som, influx-som, grafana-som, simulator.
- `compose.cam.yml`: mqbroker-cam, nodered-cam, influx-cam, grafana-cam.

`compose.all.yml` meng-`include` keduanya untuk mode dev satu mesin. Di mode itu, `compose.all.env` mengarahkan bridge ke `mqbroker-cam` lewat jaringan Docker, sehingga `CAM_IP` diabaikan.

**Satu `.env` yang sama untuk semua mesin.** Buat dari template (`cp .env.example .env`); `.env` sendiri tidak di-commit. Salin file yang sama ke kedua mesin; biasanya hanya `ROLE` yang berbeda:

| Mesin | `ROLE` |
|---|---|
| Dev (satu mesin) | `ROLE=all` |
| SOM | `ROLE=som` |
| CAM | `ROLE=cam` |

Isi `.env` di bagian atas:
- `CAM_IP` ditulis sekali saja. Dari situ diturunkan alamat bridge (`CAM_IP:1885`), target `check.sh` (`CAM_IP:8087`), dan target `outage.sh link`. Kalau `ROLE=som` tapi `CAM_IP` kosong, compose langsung berhenti dengan pesan error.
- `SOM_IP` opsional, hanya supaya `check.sh` juga bisa dijalankan dari CAM.
- `COMPOSE_PROFILES=sim` untuk simulator. Kosongkan kalau alat asli sudah tersambung.
- Password.

`COMPOSE_FILE=compose.${ROLE}.yml` di bagian bawah memilih file compose secara otomatis, jadi perintahnya tetap `docker compose up -d --build`.

Skrip `outage` memakai nama service, jadi jalankan di mesin tempat service itu berada: `outage cam` di CAM, sedangkan `outage som`, `bridge`, dan `link` di SOM. `check.sh` membaca Influx sisi lain lewat jaringan. `check.ps1` hanya untuk mode satu mesin.

Password di `.env` harus sama di kedua mesin (user `bridge` dipakai MQ-BRIDGE untuk login ke kedua broker). **Ganti semua password dev** sebelum dipasang di jaringan.

## Portainer (opsional)

Antarmuka web untuk melihat container, log, status, dan volume. Portainer adalah compose terpisah di `portainer/`, jadi tidak ikut terhapus oleh `docker compose down -v` stack WRW. Jalankan di tiap mesin yang ingin dipantau:

```bash
cd ~/wrw-testbed/portainer && docker compose up -d
```

Buka `https://<IP mesin>:9443`. Sertifikatnya *self-signed*, jadi terima peringatan browser. Langsung buat user admin dengan password kuat: kalau tidak dibuat dalam **5 menit** setelah start pertama, Portainer mengunci setup, dan perlu `docker compose restart` lalu coba lagi. Pilih environment **local** untuk melihat stack `wrw-som` atau `wrw-cam`.

Portainer punya kontrol penuh atas Docker (setara root), jadi jangan buka port 9443 ke internet.

## Alat asli: Alcor Solar Seeing Monitor

`devices/alcor/alcor_ssm_mqtt.py` adalah skrip manufaktur (`test_CSSMS_AllOS.py`, tidak disertakan di repo) yang diubah supaya mengirim MQTT.
- Yang sama dengan aslinya: perintah HID (0x80, 0x81), susunan byte, dan rumus seeing/r₀. Hasil decode-nya sudah diuji identik dengan skrip asli.
- Yang berbeda: berjalan tanpa interaksi, connect ulang sendiri kalau USB atau broker putus, dan mengirim JSON ke `pubdata/alcor/seeing` tiap `ALCOR_INTERVAL` (2 detik).
- Pengiriman memakai QoS 1 dengan session persisten, jadi data tidak hilang saat MQ-BRIDGE restart.

Skrip ini dijalankan **di host Pi SOM** (bukan container), karena butuh akses USB:

```bash
cd ~/wrw-testbed/devices/alcor
sudo cp 99-alcor-ssm.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG plugdev $USER                 # lalu login ulang
python3 -m venv venv && venv/bin/pip install -r requirements.txt
set -a; . ../../.env; set +a                   # DEVICE_PASS, BRIDGE_PORT
venv/bin/python alcor_ssm_mqtt.py --stdout --once   # cek alat: cetak 1 pengukuran, tanpa MQTT
```

Kalau `pip install hidapi` gagal di Pi, pasang dulu `sudo apt install libusb-1.0-0-dev libudev-dev`.

Skrip butuh **cython-hidapi** (modul `hid` atau `hidraw`, API `hid.device()`) seperti skrip manufaktur. Baris pertama output skrip menunjukkan modul HID yang dipakai.

**Jangan pakai `python3-hidapi` dari apt di Trixie.** Paket itu memasang `hidapi.py`, binding lain (cffi) dengan API berbeda.
- **Pi OS Trixie (Debian 13):** `python3-paho-mqtt` dari apt sudah 2.1. cython-hidapi dipasang lewat pip di venv yang bisa melihat paket apt:
  ```bash
  python3 -m venv --system-site-packages venv && venv/bin/pip install hidapi
  ```
- **Pi OS Bookworm:** `python3-paho-mqtt` masih 1.6. Buat venv yang bisa melihat paket apt, lalu pasang paho 2.x lewat pip:
  ```bash
  python3 -m venv --system-site-packages venv && venv/bin/pip install paho-mqtt==2.1.0
  ```

Supaya jalan otomatis, jadikan service. Sesuaikan `User` dan path di file service kalau perlu:
```bash
sudo cp alcor-ssm.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now alcor-ssm
journalctl -u alcor-ssm -f
```

Kalau alat asli sudah tersambung, matikan simulator (`COMPOSE_PROFILES=` kosong), supaya topik `pubdata/alcor/seeing` tidak terisi dari dua sumber sekaligus.

Catatan:
- Rentang nilai ADU mentah alat asli belum diketahui. Simulator membalik rumus manufaktur supaya seeing berada di 1–5″, tapi nilai mentahnya mungkin berbeda dari alat sungguhan. Setelah ada output `--stdout` dari alat asli, simulator dan batas QC bisa disesuaikan.
- Malam hari `valid_seeing=0`, sehingga `seeing_arcsec`, `r0`, dan `quality` tidak dikirim. Nilai mentah tetap dikirim.

## Tes di 2 Raspberry Pi

### Persiapan (kedua Pi)

1. **Raspberry Pi OS 64-bit** (Lite cukup). Pastikan `uname -m` menghasilkan `aarch64`, karena InfluxDB 1.12 tidak tersedia untuk armv7/32-bit.
2. Pasang Docker dengan skrip resmi dari docs.docker.com ("Install using the convenience script"), lalu `sudo usermod -aG docker $USER` dan login ulang. Cek dengan `docker compose version`.
3. **Jam harus benar di kedua Pi.** Pi tidak punya RTC.
   - SOM: timestamp plugin berasal dari jam SOM.
   - CAM: `delay_s` dihitung dari jam CAM.
   - Cek `timedatectl` sampai muncul `System clock synchronized: yes`.
   - Supaya container tidak start sebelum jam tersinkron saat boot:
     ```bash
     sudo systemctl enable systemd-time-wait-sync
     sudo mkdir -p /etc/systemd/system/docker.service.d
     printf '[Unit]\nAfter=time-sync.target\nWants=time-sync.target\n' | sudo tee /etc/systemd/system/docker.service.d/wait-time.conf
     sudo systemctl daemon-reload
     ```
   - Kalau lokasi tanpa internet, jadikan salah satu Pi server NTP (chrony) untuk Pi lainnya, atau pasang modul RTC/GPS.
4. Salin folder ini ke kedua Pi, misalnya dengan `scp -r wrw-testbed pi@<IP>:~/`. `.env` harus ikut disalin (file tersembunyi).
5. Catat IP CAM (`hostname -I`). Sebaiknya pakai IP statis atau reservasi DHCP. Jangan isi `CAM_IP` dengan `rpi-1.local`, karena container Alpine tidak bisa resolve mDNS.

### Menyalin file ke Pi (WinSCP/SFTP)

- Dari `nodered/*/data` cukup salin `flows.json`, `flows_cred.json`, dan `settings.js`. File lain di folder itu (`package.json`, `.config.*.json`, `lib/`, `node_modules/`) dibuat sendiri oleh Node-RED saat jalan. Jangan disalin; kalau perlu, pasang *exclude mask* di WinSCP.
- Node-RED berjalan sebagai `NODERED_UID:NODERED_GID` (default 1000:1000, biasanya user pertama di Pi). Cek dengan `id -u` dan `id -g`; kalau berbeda, sesuaikan di `.env`.
- Kalau muncul `Permission denied` saat menyalin, ada file milik root di Pi (sisa versi lama yang menjalankan Node-RED sebagai root). Perbaiki sekali dengan:
  ```bash
  sudo chown -R $USER:$USER ~/wrw-testbed
  ```

### Kalau Pi tersambung lewat WiFi

- **Matikan power saving WiFi.** Default-nya aktif di Pi dan menyebabkan latensi tinggi atau koneksi putus-sambung. Pi OS Bookworm memakai NetworkManager:
  ```bash
  nmcli -t -f NAME,TYPE connection show --active      # cari nama koneksi wifi
  sudo nmcli connection modify "<nama>" 802-11-wireless.powersave 2
  sudo nmcli connection up "<nama>"
  iw dev wlan0 get power_save                         # harus: Power save: off
  ```
- **Pastikan kedua Pi bisa saling menjangkau.** Jalankan `ping <IP CAM>` dari SOM. WiFi kampus atau tamu sering memakai *client isolation*, sehingga perangkat dalam SSID yang sama tidak bisa saling connect. Kalau begitu, pakai router atau hotspot sendiri.
- **Country WiFi** diatur lewat `sudo raspi-config` → Localisation → WLAN Country, supaya kanal 5 GHz bisa dipakai.
- Pantau kualitas sinyal dengan `iw dev wlan0 link` (signal lebih baik dari −70 dBm) dan `ping -c 100 <IP CAM>` (cek packet loss).
- `BRIDGE_CAM_KEEPALIVE=20` di `.env` membuat bridge sadar link putus dalam ±30 detik, bukan ±90 detik.

### `.env` per Pi

Siapkan satu `.env` (isi `CAM_IP` dan password), lalu salin ke kedua Pi. Setelah itu ubah satu baris saja di masing-masing Pi:

| Pi CAM | Pi SOM |
|---|---|
| `ROLE=cam` | `ROLE=som` |

Ubah langsung di Pi dengan:
```bash
sed -i 's/^ROLE=.*/ROLE=cam/' .env
```
Ganti `cam` dengan `som` untuk Pi SOM. Cek file compose yang terpilih dengan `docker compose config --services`.

### Menjalankan

Nyalakan **CAM dulu**, baru SOM. Build mqbridge di Pi butuh beberapa menit dan akses internet (Docker Hub, GitHub, Alpine, PyPI).

```bash
docker compose up -d --build      # di CAM, lalu di SOM
docker compose ps                 # influx-* harus (healthy)
docker compose logs -f mqbridge   # di SOM: cari "Connecting bridge som-to-cam" tanpa error berulang
```

Dari SOM, cek apakah port CAM terjangkau dengan `nc -zv <IP CAM> 1885`. Node-RED: `http://<IP SOM>:1880` dan `http://<IP CAM>:1881`.

### Skenario uji

| Uji | Cara | Hasil yang diharapkan |
|---|---|---|
| Normal | biarkan 10 menit, lalu `./scripts/check.sh 10m` di SOM | jumlah titik SOM = CAM |
| Link putus | `./scripts/outage.sh link 180` di SOM (butuh sudo; trafik bridge→CAM di-DROP diam-diam, SSH tetap jalan) | SOM tetap jalan; setelah tersambung lagi CAM menyusul, tanpa angka 0 per menit, `delay_s` membesar |
| WiFi CAM hilang | jauhkan Pi CAM dari AP, atau matikan AP sebentar | sama seperti link putus |
| CAM mati listrik | cabut power Pi CAM, lalu nyalakan lagi | sama seperti link putus; container start sendiri |
| Bridge restart | `./scripts/outage.sh bridge` di SOM | antrean selamat; hanya ±3 detik data QoS 0 hilang |
| SOM reboot | `sudo reboot` di SOM | timestamp setelah boot benar (cek jam `timedatectl`) |

`outage.sh link` paling mirip dengan WiFi hilang: koneksi TCP putus tanpa pemberitahuan, jadi bridge baru sadar setelah keepalive habis. Jangan mematikan WiFi Pi lewat SSH yang juga memakai WiFi (`nmcli radio wifi off`), karena SSH ikut putus dan WiFi tidak akan menyala lagi sendiri.

### Catatan Pi

- Influx dan antrean bridge menulis terus ke disk. Untuk tes singkat SD card cukup, tetapi untuk pemakaian lama gunakan SSD lewat USB.
- RAM 2 GB cukup untuk satu sisi. Pantau dengan `docker stats`.
- Influx (auth mati) dan Node-RED (tanpa login) terbuka di LAN. Ini boleh untuk tes, tapi jangan untuk jaringan publik.

## Hasil uji

Diuji dengan Mosquitto 2.0.22 + plugin WRW (dikompilasi) + 2× Node-RED 4 + endpoint tiruan `/write` Influx. Skenario: CAM mati 40 detik, dan MQ-BRIDGE di-restart (SIGTERM) di tengahnya.

- CAM menerima **semua** pesan yang diterima SOM (157/157 per stream). Timestamp-nya identik dengan SOM sampai ke nanodetik, dengan delay maksimum 45 detik.
- Antrean untuk CAM tetap utuh walau bridge di-restart, karena tersimpan di persistence.
- Pesan QoS 0 dari device ikut diantrekan (`upgrade_outgoing_qos`).
- **Yang hilang** hanya pesan yang dikirim device dalam ±3 detik saat MQ-BRIDGE sedang restart. Selama itu device tidak punya tempat publish, dan pesan QoS 0 langsung dibuang oleh client-nya. Ini titik lemah arsitektur, bukan bug.
  - Kalau alatnya bisa, pakai QoS 1 dengan session persisten. Client akan menahan pesan sampai bridge hidup lagi.
  - Restart bridge sebaiknya dijadwalkan.

Catatan: data dalam detik-detik pertama saat stack pertama kali dinyalakan tidak tersimpan, karena Node-RED belum pernah subscribe. Setelah itu, session persisten di broker yang menahan data selama Node-RED mati.
