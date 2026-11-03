# myFlowNet Windows kurulumu

`myFlowNet-<sürüm>-Setup.exe` her şeyi içeren, **yönetici yetkisi istemeyen** (kullanıcı düzeyinde) bir kurulum dosyasıdır.

* Kurulum yeri: `%LOCALAPPDATA%\Programs\myFlowNet` (değiştirilebilir; yazma izni olan her klasör olur).
* Başlat menüsü: myFlowNet, Theory guide, Examples, Uninstall; isteğe bağlı masaüstü kısayolu.
* Kaldırma: Ayarlar → Uygulamalar listesinde (HKCU kaydı) veya Başlat menüsündeki *Uninstall myFlowNet*.
* Sessiz kurulum / kaldırma: `myFlowNet-0.3.0-Setup.exe /S` · `Uninstall.exe /S` · başka klasör: `/S /D=C:\Araclar\myFlowNet` (en sonda, tırnaksız).
* İçerik: gömülü Python 3.12 (64-bit), numpy, PySide6 (QtCore/QtGui/QtWidgets), OpenCASCADE (cadquery-ocp-novtk; STEP/IGES/BREP okuma), myFlowNet, örnekler ve teori kılavuzu. Bileşenlerin lisansları `licenses` klasöründe, özeti `THIRD_PARTY_NOTICES.txt` içindedir.
* Gereksinim: Windows 10 (1703 veya üstü) / Windows 11, 64-bit. Ayrı bir Python kurulumu gerekmez, sistemdeki Python'a dokunulmaz.

Kurulum dosyası imzasız olduğu için Windows SmartScreen ilk açılışta "Windows bilgisayarınızı korudu" uyarısı gösterebilir: *Ek bilgi → Yine de çalıştır*. Kurum içi dağıtımda kod imzalama sertifikasıyla imzalanması önerilir (`signtool sign /fd sha256 /tr <timestamp-url> /td sha256 /f cert.pfx Setup.exe`). Bazı kurumsal politikalar (AppLocker) kullanıcı klasörlerinden program çalıştırmayı engelleyebilir; bu durumda BT'nin izin verdiği bir klasör seçin.

## Yeniden oluşturma

`build_installer.py` Windows'ta veya Linux'ta çalışır (Python ≥ 3.10, `pip install pefile pillow PySide6`, NSIS `makensis`):

```
python -m pip download --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp ^
       -d wheels numpy PySide6-Essentials cadquery-ocp-novtk
python installer\build_installer.py --embed python-3.12.10-embed-amd64.zip --wheels wheels --out dist
```

Adımlar: gömülü Python açılır ve `python312._pth` uygulama klasörünü (`..\app`) ve `Lib\site-packages`'ı yola ekleyecek şekilde yazılır → wheel'ler açılır → kullanılmayan Qt modülleri, araçlar, `.pyi`/`.lib` dosyaları silinir ve DLL'ler, yüklenen modüllerin (QtCore/QtGui/QtWidgets, numpy, OCP) PE import tablolarından çıkarılan bağımlılık kümesine indirgenir → uygulama, lisanslar ve simge eklenir → `myflownet.nsi` ile 64-bit NSIS kurulum dosyası üretilir (LZMA solid).

**Python çalışma ortamının kaynağı.** Bu sürüm, derleme ortamından python.org'a erişilemediği için PyPI'daki `python-embed` paketinden alınan resmi Windows gömülü dağıtımıyla (Python 3.12.9) üretildi. Bütün `.exe`/`.dll`/`.pyd` dosyalarının Authenticode imzaları doğrulandı (Python Software Foundation ve Microsoft imzaları, özetler eşleşiyor); standart kütüphane arşivi `python312.zip` imzasız olduğundan ayrıca doğrulanamadı. Kurum içi dağıtım için `--embed` seçeneğine python.org'dan indirilen resmi zip verilerek yeniden üretilmesi önerilir.

Doğrulama (Wine 9, Linux): kurulum/kaldırma, kısayollar ve kayıt girdileri; gömülü Python ile `OCP` içe aktarma, örnek STEP modelinin okunması ve üçgenlenmesi (478 yüz). Qt ve numpy, Wine'da eksik olan Windows bileşenleri (`icuuc.dll`, `ucrtbase.crealf`) nedeniyle orada denenemedi; Windows 10/11'de bu bileşenler sistemde bulunur.
