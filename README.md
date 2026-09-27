<div align="center">

<img src="assets/hero.svg" alt="Digitalvps.ir | نصب MikroTik CHR از Ubuntu یا Rescue" width="100%">

<h1>نصب میکروتیک CHR روی سرور مجازی Ubuntu</h1>

<p><strong>از Ubuntu فعال نصب را شروع کنید؛ به Rescue پنل Virtualizor نیاز نیست.</strong><br>دانلود ایمیج رسمی، بوت یک‌بارمصرف، نوشتن آفلاین دیسک و بررسی نتیجه.</p>

<p>
  <a href="#install-live"><img src="https://img.shields.io/badge/Install-Ubuntu%20%2B%20Rescue-42d9c4?style=for-the-badge" alt="دو روش نصب Ubuntu و Rescue"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Digitalvps-Ir/Mikrotik-Ubuntu?style=for-the-badge&amp;color=48c9b0" alt="مجوز MIT"></a>
  <a href="https://mikrotik.com/download/chr"><img src="https://img.shields.io/badge/CHR-Official%20RAW%20image-5797ff?style=for-the-badge" alt="ایمیج رسمی CHR"></a>
</p>

<p>
  <a href="#install-live">نصب بدون Rescue</a> ·
  <a href="#install-rescue">نصب از Rescue</a> ·
  <a href="#plans">پلن و قیمت روز</a> ·
  <a href="README.en.md">English</a>
</p>

</div>

> [!CAUTION]
> **این نصب تمام اطلاعات دیسک مقصد و خود Ubuntu را پاک می‌کند.** پیش از اجرا، بکاپ خارج از سرور، نام دیسک و دسترسی واقعی به کنسول/VNC پنل را بررسی کنید. بوت و شبکهٔ CHR روی VPS واقعی هنوز آزمون انتهابه‌انتها نشده‌اند؛ برای سرور مهم ابتدا روی یک VM آزمایشی بررسی کنید.

## 🧭 کدام روش برای من است؟

| وضعیت شما | روش | چه اتفاقی می‌افتد؟ |
| --- | --- | --- |
| Ubuntu روی VPS فعال است و Rescue ندارید | **نصب معمولی، پیش‌فرض** | ایمیج آماده می‌شود؛ بوت بعدی پیش از mount ریشه، دیسک را می‌نویسد. |
| Rescue مستقل دارید و دیسک مقصد mount نیست | **`--mode rescue`** | ایمیج همان‌جا روی دیسک آفلاین نوشته و مقایسه می‌شود. |

<div align="center">
<img src="assets/boot-flow.gif" alt="مسیر نصب: Ubuntu، محیط نصب در RAM، سپس RouterOS CHR" width="780">
</div>

این ابزار **نصب تازهٔ RouterOS CHR** است؛ Ubuntu را حفظ نمی‌کند و برای ارتقای RouterOS نصب‌شده به کار نمی‌رود. فقط فایل **RAW x86_64** را از دامنهٔ رسمی MikroTik می‌گیرد. IP، gateway، رمز و فایروال Ubuntu به CHR منتقل نمی‌شوند.

<a id="install-live"></a>
## 🚀 نصب از Ubuntu بدون Rescue

**پیش‌نیاز:** ماشین مجازی x86_64 با **Legacy BIOS**، Ubuntu دارای GRUB و `initramfs-tools`، **۲ GiB RAM پیشنهادی**، فضای کافی در `/tmp` و `/boot`، و کنسول قابل دسترس. اسکریپت مقدار `MemTotal` کمتر از ۱ GiB را رد می‌کند؛ RAM اسمی ۱ GiB ممکن است از این بررسی عبور نکند. این اسکریپت در حالت UEFI متوقف می‌شود. روی کانتینر یا هاست Virtualizor اجرا نکنید.

ابتدا دیسک، نوع بوت و بکاپ را بررسی کنید:

```bash
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL
findmnt -no SOURCE /
if test -d /sys/firmware/efi; then echo UEFI; else echo BIOS; fi
```

سپس وابستگی‌ها و اسکریپت را بگیرید. اسکریپت را پیش از اجرای root بخوانید:

```bash
sudo apt-get update
sudo apt-get install -y curl unzip util-linux coreutils busybox initramfs-tools grub2-common
curl -fL https://raw.githubusercontent.com/Digitalvps-Ir/Mikrotik-Ubuntu/main/script.sh -o script.sh
less script.sh
sudo bash script.sh --version 7.24.4
```

اسکریپت در حالت تک‌دیسک، دیسک حامل ریشهٔ Ubuntu را پیدا می‌کند. اگر نتوانست با اطمینان انتخاب کند، نام **کل دیسک** را بدهید؛ مثلاً `--disk /dev/vda`، نه `/dev/vda1`. برای ادامه باید عبارت دقیق نمایش‌داده‌شده، مانند `ERASE /dev/vda`، را تایپ کنید.

پس از آماده‌سازی، VM خودکار reboot می‌شود. مرحلهٔ نوشتن دیسک در initramfs، **پیش از mount شدن Ubuntu** اجرا می‌شود؛ پس از مقایسهٔ بایت‌به‌بایت، بوت بعدی CHR را بالا می‌آورد. هر دو بوت را از کنسول پنل دنبال کنید. SSH اوبونتو قطع خواهد شد.

<details>
<summary>اگر نصب آماده شد اما هنوز reboot شروع نشده، چگونه لغو کنم؟</summary>

```bash
sudo bash script.sh --cancel-live
```

اسکریپت معمولاً بلافاصله پس از آماده‌سازی reboot می‌کند؛ این فرمان تنها تا قبل از آغاز بوت نصب کاربرد دارد.

</details>

<a id="install-rescue"></a>
## 🛟 نصب از Rescue

در Rescue مستقل، دیسک مقصد و پارتیشن‌هایش باید **unmount** باشند. روی Rescue مبتنی بر Ubuntu/Debian ابزارهای پایه را نصب کنید، سپس نام دیسک را با `lsblk` بررسی کنید:

```bash
sudo apt-get update
sudo apt-get install -y curl unzip util-linux coreutils busybox
lsblk -o NAME,TYPE,SIZE,MOUNTPOINTS,MODEL
curl -fL https://raw.githubusercontent.com/Digitalvps-Ir/Mikrotik-Ubuntu/main/script.sh -o script.sh
less script.sh
sudo bash script.sh --mode rescue --disk /dev/vda --version 7.24.4
```

`/dev/vda` فقط نمونه است. پس از پیام `byte-for-byte verification succeeded`، Rescue را در پنل غیرفعال و VM را از پنل power cycle کنید. اگر `/tmp` کوچک است، `--workdir /path` را روی فضایی **خارج از دیسک مقصد** قرار دهید.

## 🧩 نسخه‌ها و سازگاری

| انتخاب | وضعیت در ۲۷ سپتامبر ۲۰۲۶ | نکته |
| --- | --- | --- |
| `7.24.4` | Stable | نمونهٔ فرمان‌های بالا |
| `7.23.7` | Long-term | قابل انتخاب با `--version 7.23.7` |
| `6.49.22` | قدیمی | فقط برای نیاز سازگاری؛ محدودیت‌های CHR v6 را بخوانید. |

اسکریپت هر شمارهٔ **عددی** رسمی از سری 6 یا 7 را می‌پذیرد؛ برای نسخهٔ تازه‌تر لازم نیست فهرست اسکریپت عوض شود. البته فایل RAW همان نسخه باید در [صفحهٔ رسمی CHR](https://mikrotik.com/download/chr) موجود باشد. beta/development با نام‌های غیرعددی در این مسیر پذیرفته نمی‌شوند. «پذیرفته‌شدن شماره» تضمین بوت روی همهٔ مجازی‌سازها نیست.

| محدودیت این پروژه | توضیح |
| --- | --- |
| معماری و firmware | فقط x86_64 و Legacy BIOS در این مسیر نصب |
| انتخاب دیسک در Ubuntu | دیسک مقصد باید دیسک ریشهٔ Ubuntu باشد؛ تشخیص خودکار فقط وقتی یک دیسک ریشه پیدا شود |
| شبکهٔ نخستین بوت | نیازمند کنسول و تنظیم متناسب با IP، prefix، gateway و NIC سرویس شما |
| اعتبارسنجی | بررسی ساختار ZIP و ایمیج، امکان SHA-256 مرجع با `--sha256`، و مقایسهٔ دادهٔ نوشته‌شده |
| آزمون واقعی | بررسی‌های CI و ساخت initramfs انجام شده؛ بوت CHR و دسترسی شبکه روی VPS واقعی هنوز تأیید نشده است |

<a id="plans"></a>
## 🌐 پلن‌ها و قیمت روز Digitalvps.ir

برای **سرور مجازی میکروتیک** و دیگر سرویس‌ها، مشخصات، موجودی و قیمت روز را در [پنل رسمی Digitalvps.ir](https://client.digitalvps.ir/) ببینید. قیمت و منابع پلن‌ها تغییر می‌کنند؛ این README عدد ثابت یا وعدهٔ تأییدنشده منتشر نمی‌کند.

پیش از سفارش برای اجرای این اسکریپت، از پشتیبانی دربارهٔ **Legacy BIOS، نوع دیسک مجازی، دسترسی کنسول و امکان بوت CHR** روی پلن مدنظر سؤال کنید. وجود پلن VPS به‌تنهایی به معنی سازگاری این روش نصب با آن پلن نیست.

## 🔐 بعد از اولین بوت

از کنسول وارد RouterOS شوید و فوراً برای کاربر `admin` رمز قوی بگذارید؛ ایمیج تازهٔ رسمی ممکن است با رمز خالی شروع شود. سپس رابط، IP/prefix، gateway، DNS و محدودیت دسترسی سرویس‌های مدیریتی را طبق اطلاعات همان VPS تنظیم کنید. به دسترسی SSH یا DHCP پس از نصب اتکا نکنید.

## 🛠 عیب‌یابی سریع

| نشانه | بررسی بعدی |
| --- | --- |
| دیسک `mounted or in use` | در Rescue، mount و swap دیسک را بررسی کنید؛ از Ubuntu فعال، حالت پیش‌فرض را اجرا کنید. |
| دیسک ریشه شناسایی نشد | خروجی `findmnt` و `lsblk` را بررسی کنید؛ در صورت لزوم `--disk` را برای **دیسک ریشه** بدهید. |
| پیام UEFI یا GRUB | این مسیر به Legacy BIOS و GRUB نیاز دارد؛ تنظیمات firmware/boot را در پنل کنترل کنید. |
| دانلود یا ZIP نامعتبر | نسخه و دسترسی به `download.mikrotik.com` را بررسی کنید؛ نوشتن دیسک هنوز آغاز نشده است. |
| خطای نوشتن یا مقایسه | دیسک ممکن است ناقص باشد؛ از کنسول/Rescue عیب‌یابی کنید و آن را بوت نکنید. |
| CHR بالا آمد ولی شبکه ندارد | از کنسول، NIC، MAC، IP/prefix و gateway واقعی سرویس را بررسی کنید. |

برای گزارش خطای اسکریپت، [Issue باز کنید](https://github.com/Digitalvps-Ir/Mikrotik-Ubuntu/issues). رمز، IP خصوصی مشتری، شماره‌سریال و اطلاعات حساب را از لاگ حذف کنید.

## 📚 منابع

- [دانلود رسمی CHR و نسخه‌های روز](https://mikrotik.com/download/chr)
- [راهنمای رسمی نصب CHR](https://manual.mikrotik.com/docs/getting-started/installation-and-upgrade/install/chr-installation/)
- [لایسنس رسمی CHR](https://manual.mikrotik.com/docs/getting-started/routeros-licensing/chr/chr-licensing/)
- [مجوز MIT این پروژه](LICENSE)

<div align="center"><strong>Digitalvps.ir</strong> · ابزار مستقل و متن‌باز نصب CHR</div>
