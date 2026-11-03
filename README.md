# myFlowNet

Gaz türbini ikincil hava sistemleri (SAS) için 1D akış ağı çözücüsü ve grafik arayüzü.

Ağ, **odalar** (boundary, plenum, momentum, inertial) ve onları bağlayan **elemanlardan** kurulur. Çözücü basınç, debi, toplam sıcaklık ve girdap (swirl) dağılımını sıkıştırılabilir akış, dönen çerçeve ve rotor işi etkileriyle birlikte hesaplar. Formülasyonun ayrıntıları `docs/THEORY.md` içindedir (GUI'de Help → Theory guide, F1).

## Eleman kütüphanesi

| Eleman | Model |
|---|---|
| Orifice / Hole | İzentropik sıkıştırılabilir orifis, sabit Cd veya McGreehan & Schotsch (r/d, L/d); dönen delik (bağıl toplam basınç, rothalpi, Euler işi), ön-girdap nozulu (çıkış açısı) |
| K-Loss | Çıkış dinamik basıncına göre K (Miller §7.7 / Flow Simulator, varsayılan) veya giriş tanımı; boğulma |
| Pipe / Channel | 1D sıkıştırılabilir yürütme: Colebrook sürtünme, Gnielinski ısı transferi, kesit değişimi, radyal pompalama |
| Labyrinth Seal | Diş-diş (St-Venant / Neumann, Chaplygin Cd, Vermes / Hodkinson taşınım), son diş boğulması, Martin–Egli; rotor/stator sürtünmesiyle girdap ve rüzgâr ısınması |
| Vortex | Serbest / zorlanmış girdap basınç oranı, rotor işi |
| Rotor-Stator Cavity | Radyal yürütme: açısal momentum + radyal denge, Daily & Nece kalibrasyonlu duvar sürtünmesi, rüzgâr ısınması |
| Fixed Flow, Disc Pumping | Verilen debi; disk sınır tabakası pompalaması (Sultanian / Owen & Rogers) |

**Momentum odası:** giren jetlerin geçiş hızını taşır; aşağı akıştaki eleman bu dinamik basıncın cos²θ kadarını geri kazanır (θ: oda hızı ile elemanın `Flow direction φ` parametresi arasındaki açı; Nart, TEI FlowNet). Yönleri tuvaldeki çizimden almak için: Model → Set element flow directions from the drawing. Flow Simulator ile karşılaştırma: Examples → Momentum chambers (Nart / Flow Simulator) ve `docs/THEORY.md` §5.1.

## Arka plan CAD geometrisi

Ağ, motorun STEP / IGES / BREP / STL modelinin üzerine çizilebilir (Flow Simulator'daki *Load CAD Model* gibi): **File → Load background geometry** (Ctrl+G) ve sağdaki **Background** paneli.

* **Kesit ve görünüm:** motor ekseni (X/Y/Z), kesit açısı θ; *Meridional* görünümde tuval = eksenel × yarıçap, *3D view* / yaw-tilt ile kesilmiş model döndürülür. Kesit yüzleri parça renkleriyle doldurulur, arkadaki yüzeyler gölgeli ve soluk çizilir.
* **Ağ araçları:** odaları CAD köşe noktalarına yakalama, oda referans yarıçaplarını konumdan alma (Model → Set chamber radii from background geometry), durum çubuğunda imlecin eksenel konumu ve yarıçapı; görünüm döndüğünde ağ kesitle birlikte hareket eder.
* **Yerleşim:** ölçek (px/mm), *Fit to network*, *Move / scale on canvas*. Ayarlar ve dosya yolu (göreli) model dosyasında saklanır.
* **Okuyucu:** STEP/IGES için OpenCASCADE gerekir — `python -m pip install -r requirements-cad.txt` (cadquery-ocp; yoksa program yüklemeyi teklif eder). Alternatif: `python -m pip install gmsh`. STL ek paket gerektirmez.

Örnek: Examples → **HPT pre-swirl system on CAD geometry** (`examples/geometry/hpt_preswirl_rig.step`).

## Kurulum (Windows)

**Hazır kurulum dosyası:** [`dist/myFlowNet-0.3.0-Setup.exe`](dist/myFlowNet-0.3.0-Setup.exe) (59 MB; GitHub'da dosya sayfasındaki *Download raw file* düğmesiyle indirilir) — Python dahil her şeyi içerir, yönetici yetkisi istemez (`%LOCALAPPDATA%\Programs\myFlowNet`). Ayrıntılar ve yeniden oluşturma: `installer/README.md`.

**Kaynaktan çalıştırma:**

1. Python 3.10 veya üstü kurulu olmalı.
2. Bu klasörde bir komut istemi açın:

```
python -m pip install -r requirements.txt
python -m pip install -r requirements-cad.txt     (isteğe bağlı: STEP / IGES arka planı)
```

3. Arayüzü başlatmak için `run_myflownet.bat` dosyasına çift tıklayın ya da:

```
python -m myflownet
python -m myflownet examples\preswirl_system.json
```

Program açıldığında HP türbin ön-girdap soğutma sistemi örneği yüklenir ve çözülür.

## Arayüz

Yerleşim, Flow Simulator kullanıcılarının alıştığı iş akışını izler (ikonlar ve çizimler myFlowNet'in kendisine aittir):

* **Element Library (sol üst):** oda ve eleman tipleri kategorilere ayrılmış ağaç (Chambers, Restrictions, Tubes, Seals, Rotating cavities, Sources). Odayı tuvale **sürükleyip bırakın**; elemanı yukarı akış odasının üzerine bırakıp aşağı akış odasına tıklayın. Tıklayıp seçmek de çalışır (Shift ile birden çok yerleştirme, Esc seçim moduna döner).
* **Model Browser (sol alt):** odalar, elemanlar (tipe ya da ID'ye göre), rotorlar ve arka plan geometrisi; ad/ID filtresi; seçim tuval ile eşzamanlı, çift tıklama öğeyi ortalar.
* **Property Editor (sağ):** Parametre | Değer | Birim tablosu. Zorunlu girdiler mavi; az kullanılanlar *Show more*, çözücü düzeyindekiler *Advanced options* altında. Aynı tipte birden çok öğe seçilince ortak girdiler birlikte düzenlenir (farklı değerler "(mixed)"); karışık seçimi *Selection filter* tek tipe indirir. Elemanın bağlantısı (yukarı/aşağı akış odası) buradan değiştirilebilir. **Background Geometry** sekmesi CAD arka planı içindir.
* **Output (alt):** Info (seçimin bağlantıları, sonuç özeti, model kontrolü), Output (çözücü günlüğü), Chamber / Element Results tabloları, Convergence, Distribution.
* **Menüler:** File · Edit · View · Tools · Pre-Processing · Solver · Post-Processing · Help.
* **Modelleme penceresi (View menüsü):** arka plan *Blue* (varsayılan) / *Black* / *Gradient* (iki renk seçilir) / *Light*; etiketler *ID + name / Name / ID / None*; *Results on model*; *Symbols as wireframe*; bağlantı çizgisi kalınlığı; global eksenler. Uygulama stili: *Classic* (varsayılan), *Modern light*, *Modern dark*. Paneller taşınabilir/kapatılabilir; *View → Reset layout* varsayılana döner.
* **Post-Processing → Colorize:** odaları (statik/toplam basınç, Tt, K, yoğunluk, referans yarıçapı) veya elemanları (debi, Δp, çıkış Tt, Mach, çap) kontur renkleriyle boyar. *Contour / legend settings*: seviye sayısı (2–32 bant ya da sürekli), dinamik/sabit ölçek (min/max), gökkuşağı veya tek renk, ters renk, sabit/bilimsel sayı biçimi ve hane sayısı, modelde MIN/MAX işaretleri.
* Tekerlek: yakınlaştırma · orta tuş veya Alt+sürükle: kaydırma · Del: sil · Ctrl+A: tümünü seç · Ctrl+Z / Ctrl+Y: geri al / yinele · sağ tık: elemanı ters çevir, odayı çoğalt.

## Komut satırı

```
python -m myflownet solve examples\preswirl_system.json sonuc.json
```

Özet tabloyu yazar, isteğe bağlı olarak tüm sonuçları JSON'a kaydeder.

Python'dan kullanım:

```python
from myflownet import Network, solve
net = Network("Örnek")
a = net.add_chamber("boundary", "Besleme", p=3e5, T=500.0)
c = net.add_chamber("plenum", "Ara oda")
b = net.add_chamber("boundary", "Çıkış", p=1e5, T=300.0, p_type="static")
net.add_element("orifice", a.id, c.id, diameter=10e-3, cd=0.7)
net.add_element("labyrinth", c.id, b.id, n_teeth=4, radius=0.12, clearance=0.3e-3)
sol = solve(net)
print(sol.message, sol.elements[1]["mdot"])
```

Tüm girdiler SI birimindedir (Pa, K, m, kg/s); GUI gösterim birimlerini dönüştürür.

## Testler

```
python -m pip install pytest
python -m pytest -q
```

Kapalı-form çözümlere karşı doğrulama: izentropik orifis, Fanno akışı, boğulma, Neumann labirent formülü, girdap basınç oranları, kapalı kavite çekirdek girdabı, Euler işi, ön-girdap bağıl sıcaklığı, enerji korunumu (ayrıntı: `docs/THEORY.md` §5).

CAD arka planı (`tests/test_cad.py`): STL okuma ve düğüm birleştirme, kesit halkalarının yarıçapları (dikiş düzleminde tam, kiriş ortasında cos(π/n)), kırpmada alan korunumu, görünüm eşlemesinin tersinirliği, değen katıların ayrı halkaları, model dosyasında göreli yol; STEP okuma ve örnek düzeneğin kesiti (cadquery-ocp / gmsh kuruluysa).

## Klasör yapısı

```
myflownet/
  fluid.py          gaz özellikleri (NASA polinomları, Sutherland)
  compressible.py   izentropik bağıntılar, akış fonksiyonu
  correlations.py   sürtünme, Nu, Cd düzeltmeleri, labirent, disk korelasyonları
  elements/         eleman kütüphanesi (base, orifice, loss, pipe, labyrinth, vortex, source)
  model.py          ağ veri modeli ve JSON dosya biçimi
  cad.py            STEP / IGES / BREP / STL okuma ve üçgenleme (OpenCASCADE, gmsh, numpy)
  geomview.py       kesit düzlemi, kırpma, kesit halkaları, 3B izdüşüm
  solver.py         Newton (SASS) çözücü, enerji ve girdap güncellemesi
  examples.py       hazır örnek ağlar
  gui/              PySide6 arayüzü (background.py: CAD arka plan katmanı ve paneli)
docs/THEORY.md      teori kılavuzu
examples/*.json     örnek modeller
examples/geometry/  örnek CAD modeli (STEP) ve onu üreten betik
tests/              doğrulama testleri
```

## Yeni eleman eklemek

`myflownet/elements/` altında `TwoPortMass` (debi = f(basınç)) veya `Element` (basınç oranı tipi, `category = "pressure"`) sınıfından türetin, `PARAMS` listesini `ParamSpec` ile tanımlayın ve `@register` ile kaydedin. Kütle tipi elemanda yalnızca `forward()` (tek yönlü debi ve çıkış bilgisi) yazmak yeterlidir; akış yönü, dönen çerçeve, Euler işi ve çıkış girdabı taban sınıfta işlenir. Elemanı `elements/__init__.py` içindeki `PALETTE_ORDER` listesine eklediğinizde GUI paletinde ve özellik panelinde otomatik görünür.
