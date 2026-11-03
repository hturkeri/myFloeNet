# myFlowNet Teori Kılavuzu

Sürüm 0.3 · Gaz türbini ikincil hava sistemi (SAS) için 1D akış ağı çözücüsü

Bu kılavuz myFlowNet'in çözdüğü denklemleri, eleman modellerini ve kullanılan korelasyonları tanımlar. Formülasyon Altair Flow Simulator'ın *Solver Technical Manual*'ındaki yapıyla (oda/eleman ayrımı, dönen çerçeve, girdap elemanları, kavite çözücüsü) uyumlu kurulmuş; denklemler açık literatürden (Sultanian 2018, Owen & Rogers 1989, Shapiro 1953, Miller 1990 vb.) türetilmiştir. Kaynaklar en sondadır.

---

## 1. Ağ yapısı

Model iki tür nesneden oluşur:

* **Oda (chamber)** – toplanmış hacim. Durumu: statik basınç `p`, mutlak toplam sıcaklık `Tt`, girdap oranı `K`.
  * *Boundary* – `p` (toplam veya statik), `Tt` ve `K` sabittir; kaynak veya kuyu olabilir.
  * *Plenum* – iç oda; geçiş hızı yok (Pt = Ps), girdap kullanıcı tarafından sabitlenir (varsayılan K = 0).
  * *Momentum* – iç oda; giren jetlerin geçiş (meridyonel) hızını taşır. Aşağı akıştaki eleman bu dinamik basıncın cos²θ kadarını geri kazanır (§1.2; Nart, TEI FlowNet).
  * *Inertial* – iç oda; girdap, giren akışların açısal momentum karışımından hesaplanır.
* **Eleman (element)** – iki odayı (a → b) bağlayan akış yolu. İşaretli kütlesel debi `ṁ`, a'dan b'ye pozitiftir.
  * *Kütle tipi* elemanlar `ṁ = f(oda durumları)` ilişkisini verir (orifis, K-kaybı, boru, labirent, sabit debi, disk pompalama).
  * *Basınç tipi* elemanlar `p_b/p_a = PR(ṁ, …)` ilişkisini verir; debileri ağın ek bilinmeyenidir (serbest/zorlanmış girdap, rotor-stator kavitesi). Flow Simulator'daki vortex elemanlarıyla aynı yaklaşım.

### 1.1 Girdap oranı ve dönen çerçeve

Oda girdabı referans rotorun açısal hızı Ω_ref ile tanımlanır:

```
Vθ(r) = K · Ω_ref · r
```

Bir eleman Ω_e hızında dönüyorsa (Ω_e = 0: duran eleman) giriş yarıçapı r'de:

```
U   = Ω_e · r                       (kanat/delik hızı)
Wθ  = Vθ − U                        (bağıl teğetsel hız)
Ts  = Tt − Vθ²/(2cp)                (statik sıcaklık)
Tt,rel = Ts + Wθ²/(2cp)             (eleman çerçevesinde toplam sıcaklık)
pt,rel = p · (Tt,rel/Ts)^(γ/(γ−1))
pt,in  = p + (1 − DQ_IN) · (pt,rel − p)
```

`DQ_IN` (0…1) giriş öncesi bağıl dinamik basıncın kaybolan kısmıdır (Flow Simulator'daki DQ_IN ile aynı anlam). Varsayılan 1: sadece statik basınç sürer (girdaplı odadan dik delik). Ön-girdap alıcı deliklerinde 0'a yakın değerler kullanılır.

**Rothalpi.** Dönen bir elemanda yarıçap r_in → r_out değişirken bağıl toplam entalpi `I = cp·Tt,rel − U²/2` korunur. İzentropik pompalama ile etkin giriş durumu:

```
Tt,rel,eff = Tt,rel + (U_out² − U_in²)/(2cp)
pt,eff     = pt,in · (Tt,rel,eff/Tt,rel)^(γ/(γ−1))
```

**Euler işi.** Elemandan çıkan akışın mutlak toplam sıcaklığı:

```
Tt,abs,out = Tt,rel,out + (Vθ,out² − Wθ,out²)/(2cp),   Vθ,out = U_out + Wθ,out
⇒ cp·ΔTt = U_out·Vθ,out − U_in·Vθ,in
```

Duran elemanlarda `Tt` korunur (yalnızca kullanıcının verdiği ısı eklenir). Ön-girdap sisteminde alıcı deliği girişindeki bağıl sıcaklık düşümü bu bağıntıdan doğal olarak çıkar:

```
Tt,rel = Tt − U²·(2β − 1)/(2cp),   β = Vθ/U
```

### 1.2 Momentum odaları ve akış yönü

Ani kesit ve yön değişimlerinde, bir elemandan çıkan jetin dinamik basıncı sonraki elemana kısmen taşınır. Nart'ın FlowNet formülasyonunda düğümde hem Pt hem Ps tutulur ve elemanın giriş toplam basıncı, düğüm hızı ile eleman ekseni arasındaki θ açısına bağlıdır:

```
Pt,in = Ps · [1 + ((Pt/Ps)^((γ−1)/γ) − 1) · cos²θ]^(γ/(γ−1))      (Nart Denk. 10)
Pt,in = Pt·cos²θ + (1 − cos²θ)·Ps                                   (sıkıştırılamaz, Denk. 8)
```

myFlowNet'te momentum odası geçiş dinamik basıncı q = Pt − Ps ve yönü φ ile tanımlanır:

* Hız vektörü, giren jetlerin kütle ağırlıklı momentumudur: `V = |Σ ṁ_e·v_e| / Σ ṁ_e`; v_e eleman çıkış jet hızı, yönü elemanın `direction` parametresi φ_e (a → b; ters akışta φ_e + 180°). M ≤ 1 ile sınırlanır (Flow Simulator momentum odasıyla aynı).
* Elemanın sürücü basıncı yukarıdaki bağıntıyla, θ = φ_e − φ_oda ve cosθ < 0 ise 0 alınarak bulunur.
* Karşı basınç: bir jet, akışı kendisine doğru gelen bir momentum odasına boşalıyorsa o akışın bu yöndeki dinamik basıncını da yenmek zorundadır: `p_karşı = Pt,in(oda, φ_jet + 180°)`. Böylece ileri ve geri sürücü potansiyeller tam antisimetrik olur, akış yönü tektir ve ṁ(p) sürekli kalır (Nart'ın vurguladığı akış yönü belirleme sorunu).
* q, Newton'ın dış döngüsünde güncellenir: iç Newton q sabitken yakınsar, ardından q hedef değerine çekilir. q = 0 ile başlamak Nart'ın başlatma adımına (önce momentum aktarımı kapalı, Pt = Ps) karşılık gelir. Nart'ın Jacobian'ı da (Denk. 16) düğüm hızını iterasyonlar arasında sabit tutar.

---

## 2. Çözüm yöntemi

Yöntem NASA GFSSP'deki SASS (Simultaneous Adjustment with Successive Substitution) yaklaşımına ve Flow Simulator'ın "relaxed Newton-Raphson" çözücüsüne benzer.

### 2.1 Bilinmeyenler ve artıklar

* Her iç oda için statik basınç `p_i`.
* Her basınç tipi eleman için debi `ṁ_e`.

Artıklar:

```
Kütle (her iç oda):        R_i = (Σ ṁ_giren − Σ ṁ_çıkan) / ṁ_ölçek
Basınç oranı (her PR el.): R_e = ln p_b − ln p_a − ln PR_e(ṁ_e, durumlar)
```

### 2.2 Newton adımı

* Jacobian, eleman-yerel sonlu farklarla kurulur: her eleman yalnızca kendi iki odasına bağlı olduğundan her Newton iterasyonunda eleman başına 2–3 ek değerlendirme yeterlidir (seyrek yapı). Basınç tipi elemanlar için `∂ln PR/∂ṁ` de sonlu farkla alınır.
* Adım sınırlama: iç oda basıncı bir adımda en fazla `max_dp_frac` (varsayılan %30) oranında değişir.
* Geri izlemeli (backtracking) çizgi araması: artık normu yeterince azalmazsa adım yarıya indirilir (Armijo koşulu).
* Sıfır basınç farkı civarında `ṁ ∝ √Δp` tipi karakteristiklerin türevi sonsuza gider. Bunu önlemek için `1 − p_dn/p_t < 2·10⁻⁵` bölgesinde karakteristik doğrusallaştırılır (sonlu dṁ/dp).

### 2.3 Enerji denklemi

Her kabul edilen Newton adımından sonra iç odaların toplam entalpisi, upwind karışım denklemlerinden **doğrusal sistem** olarak doğrudan çözülür:

```
Σ_giren ṁ_e · (h_yukarı(e) + Δh_e) + Q_oda = h_oda · Σ_giren ṁ_e
```

`Δh_e`, elemanın kattığı entalpidir (dönme işi, rüzgâr ısınması, ısı girişi). Böylece geri dönüşlü (resirkülasyonlu) ağlarda da enerji tek adımda dengelenir. `Tt = h⁻¹(h)` Newton ile bulunur.

### 2.4 Açısal momentum (girdap)

Inertial odalar için:

```
K_oda = Σ ṁ_e (r·Vθ)_çıkış,e / (Σ ṁ_e · Ω_ref · r_oda²)
```

ardışık yerine koyma ile güncellenir.

### 2.5 Başlangıç ve yakınsama

* Başlangıç basınç ve sıcaklıkları, sınır değerlerinin ağ grafiği üzerinde Laplace interpolasyonuyla bulunur (topolojiye uygun, akış yönlerini doğru tahmin eder). GUI'de yeniden çözümde önceki sonuç başlangıç olarak kullanılır.
* Yakınsama: `max|R_kütle| < tol_mass` (varsayılan 10⁻⁹, bağıl), `max|R_PR| < 10⁻¹⁰`, iterasyonlar arası `ΔTt < tol_T`, `ΔK < tol_K`.

---

## 3. Gaz özellikleri

* **Kuru hava** (varsayılan): N2/O2/Ar karışımı, NASA 7-katsayılı polinomlarla `cp(T)` (GRI-Mech 3.0 verisi, 200–5000 K). Entalpi `h(T) = ∫cp dT` olarak (298.15 K referans) iki sıcaklık aralığında sürekli kurulur. `R = 287.05 J/kg/K`.
* Viskozite ve ısıl iletkenlik: Sutherland bağıntısı (μ₀ = 1.716·10⁻⁵ Pa·s, S = 110.4 K; k₀ = 0.0241 W/m/K, S = 194 K).
* **Sabit cp gazı**: doğrulama için (kapalı-form çözümlerle karşılaştırma).

İzentropik bağıntılarda γ, ilgili sıcaklıkta değerlendirilir.

---

## 4. Eleman modelleri

### 4.1 Orifis / delik / nozul (`orifice`)

```
ṁ = Cd · A · pt,eff / √(R·Tt,eff) · Ψ(π),        π = max(p_dn/pt,eff, π*)
Ψ(π) = √{ 2γ/(γ−1) · [π^(2/γ) − π^((γ+1)/γ)] },  π* = (2/(γ+1))^(γ/(γ−1))
```

π < π* ise akış boğulmuştur (choked). Jet hızı `V_j = √(2cp·Tt·(1 − π^((γ−1)/γ)))`.

**Cd modelleri**

* Sabit Cd (ileri ve ters akış için ayrı değer verilebilir).
* Keskin kenarlı ince orifis tabanı Cd₀ + McGreehan & Schotsch (1988) düzeltmeleri:

```
Köşe yarıçapı:  Cd_r = 1 − f(1 − Cd₀),  f = 0.008 + 0.992·exp(−5.5 r/d − 3.5 (r/d)²)
Boy/çap:        Cd_L = 1 − g(1 − Cd_r), g = [1 + 1.3·exp(−1.606 (L/d)²)]·(0.435 + 0.021 L/d)
```

Etkin boy, köşe yarıçapı kadar kısaltılır.

**Dönen delikler.** `rotor`, `r_a`, `r_b` girildiğinde §1.1'deki bağıl toplam basınç, rothalpi ve Euler işi otomatik uygulanır. Dönmenin Cd üzerindeki ek etkisi (insidans) için literatürdeki korelasyonlar (Dittmann vd. 2004; Idris & Pullen 2005) Cd değeri olarak girilebilir.

**Çıkış girdabı.** `auto`: duran nozulda `Vθ = V_j·sin(α)` (α: çıkış jet açısı; ön-girdap nozulları için 60–80°), dönen delikte `Vθ = U_out + V_j·sin(α)`. `conserve`: r·Vθ korunur. `fixed`: `Vθ = K·Ω·r`.

### 4.2 K-kaybı (`kloss`)

İki sıkıştırılabilir tanım vardır; sıkıştırılamaz limitte ikisi de `ṁ = A·√{2ρ(pt,in − ps,dn)/(1+K)}` verir (`Cd = 1/√(1+K)`).

**Çıkış tanımı (varsayılan; Miller §7.7, Flow Simulator, Nart Denk. 5–7).** K çıkış dinamik basıncına (½ρV² = γ/2·ps·M²) göre tanımlıdır; çıkış Mach sayısı tek bir kök bulma ile elde edilir, debi çıkış istasyonundan hesaplanır:

```
pt,in − pt,ex = K·½ρ_ex·V_ex²   ⇒   K·M_ex² + (2/γ)·(PR_ex − pt,in/ps,ex) = 0,   PR_ex = pt,ex/ps,ex
ṁ = A·pt,ex/√(R·Tt)·FF(M_ex)
f(M=1) ≤ 0 ise boğulma: M_ex = 1, pt,ex = pt,in/(1 + K·γ/(2·PR*))
```

**Giriş tanımı.** Kayıp giriş istasyonundaki sıkıştırılabilir dinamik basınca göre:

```
istasyon 1:  M1 = FF⁻¹(ṁ√(R·Tt)/(A·pt1)),       ps1 = pt1/(1 + (γ−1)/2·M1²)^(γ/(γ−1))
kayıp:       pt2 = pt1 − K·(pt1 − ps1)
çıkış:       ps2(ṁ) = p_dn  →  ṁ (Brent),  M2 = 1'de boğulma
```

Çıkış dinamik basıncı bir plenuma boşalır; momentum odası ise onu taşır (§1.2).

### 4.3 Boru / kanal (`pipe`)

Genelleştirilmiş 1D sıkıştırılabilir akış (Shapiro'nun etki katsayıları; NACA TN 3150 yaklaşımı). Dönen çerçevede, sürtünme, ısı transferi, kesit değişimi ve yarıçap değişimi (pompalama) birlikte:

```
dp/p − dT/T + dV/V = −dA/A
dp + ρV dV         = −f·ρV²/(2D)·dx + ρΩ²r·dr
cp dT + V dV       = δq + Ω²r·dr
⇒ dV = V/(1 − M²) · [ −dA/A − S2/p + S3/(cp·T) ]
   S2 = −f·ρV²/(2D)·dx + ρΩ²r·dr,   S3 = δq + Ω²r·dr
   δq = h·πD·(T_w − T_aw)·dx / ṁ
```

* Darcy sürtünme katsayısı: laminer `64/Re`; türbülanslı Colebrook-White (Haaland başlangıcı ile iteratif); 2300–4000 arası doğrusal geçiş.
* Isı transferi (seçmeli, sabit duvar sıcaklığı): Gnielinski (türbülanslı), Nu = 3.66 (laminer).
* Giriş kaybı `K_in`; çıkışta dinamik basınç boşaltılır (`ps,çıkış = p_dn`).
* Integrasyon: segment başına Heun (RK2). Debi, çıkış basıncı koşulundan sekant (önceki çözümden sıcak başlangıç) veya Brent ile bulunur. Boru içinde M → 1 olursa boğulma kabul edilir; debi arka basınçtan bağımsız hale gelir.

### 4.4 Labirent conta (`labyrinth`)

**Diş-diş (tooth-by-tooth) model** — her diş bir orifis, cepler arasında sıcaklık sabit (izentalpik):

```
St-Venant:  ṁ = Cd_i·μ_i·A·p_(i−1)/√(R·T) · Ψ(p_i/p_(i−1))
Neumann:    ṁ = Cd_i·μ_i·A·√{(p_(i−1)² − p_i²)/(R·T)}
A = 2π(r + c/2)·c
```

* İlk dişte taşınım katsayısı μ₁ = 1, sonrakilerde μ:
  * Vermes (1961): `μ = 1/√(1−α)`, `α = 8.52/((s − w)/c + 7.23)`
  * Hodkinson (1939): `μ = 1/√{1 − ((n−1)/n)·(c/s)/((c/s) + 0.02)}`
* Diş Cd'si: sabit veya Chaplygin: `Cd = π/(π + 2 − 5φ + 2φ²)`, `φ = (p_(i−1)/p_i)^((γ−1)/γ) − 1` (Micio vd. 2011'de kullanılan biçim).
* Basınç dişten dişe yürütülür; son diş boğulursa debi arka basınçtan bağımsızdır. Kalibrasyon için `flow multiplier` (bal peteği, eğik diş, dönme etkileri – Waschka vd. 1992).

**Martin–Egli toplu model:** `ṁ = Cd·μ·A·p0/√(R·T)·√{(1 − π²)/(n − ln π)}` (boğulmamış contalar için).

**Girdap ve rüzgâr ısınması.** Rotor ve stator yüzey sürtünmesi (ıslak alan = faktör·2πr·n·s, Blasius tipi cf) ile açısal momentum dengesi örtük olarak çözülür:

```
ṁ·r·(V2 − V1) = r·A·(τ_rotor(U − V2) − τ_stator(V2)),   W = Ω·r·A·τ_rotor
ΔTt = W/(ṁ·cp + |W|/ΔT_max)
```

### 4.5 Serbest ve zorlanmış girdap (`vortex`)

Radyal denge `dp/dr = ρVθ²/r` izentropik integrali:

```
Zorlanmış (Vθ = KΩr):  Ts2 = Ts1 + (KΩ)²(r2² − r1²)/(2cp)
Serbest (r·Vθ = C):    Ts2 = Ts1 + C²/(2cp)·(1/r1² − 1/r2²)
p2/p1 = (Ts2/Ts1)^(γ/(γ−1))
```

* Girdap kaynağı: sabit K veya yukarı odanın girdabı.
* Sıcaklık: "rotor işi" seçeneğinde `cp·ΔTt = Ω·Δ(r·Vθ)` (örn. K = 1 eş-dönen kavite içinde dışa akışta ısınma, içe akışta soğuma); "yok" seçeneğinde `Tt` sabit. Serbest girdapta r·Vθ korunduğundan iş yoktur.
* Serbest girdapta küçük yarıçapa inen akışta statik sıcaklık çökerse (gerçekte boğulma), eleman uyarı verir — vorteks indirgeyici gereksinimini gösteren durum.

### 4.6 Rotor-stator kavitesi (`cavity`)

Kavite r_yukarı → r_aşağı arasında N segmente bölünür. Her segmentte açısal momentum dengesi **örtük** (segment çıkış hızında) çözülür:

```
ṁ·(r2·V2 − r1·V1) = 2π·r_m²·Δr · [τ_r − τ_s]
τ_r = ½ρ·cf_r·(Ωr − V)|Ωr − V|,     τ_s = ½ρ·cf_s·V|V|
cf  = c · max(1.232·Re_r^(−1/2), 0.0534·Re_r^(−1/5)),   Re_r = ρ·|ΔV|·r/μ
```

Yerel cf sabitleri, entegre edildiğinde serbest disk moment katsayılarını verir (`Cm = 1.935 Re^(−1/2)` laminer, `Cm = 0.0729 Re^(−1/5)` türbülanslı, tek yüz; von Kármán 1921, Owen & Rogers 1989).

* Stator/rotor sürtünme oranı, debisiz kavitede çekirdek girdap oranı K₀ (varsayılan 0.426) elde edilecek şekilde seçilir: `cf_s/cf_r = ((1−K₀)/K₀)^1.8`.
* "Daily & Nece" seçeneğinde mutlak seviye, Daily & Nece (1960) kapalı disk moment katsayısına (rejim I–IV, tek yüz: `π/(G·Re)`, `1.85 G^0.1 Re^−0.5`, `0.040 G^−1/6 Re^−1/4`, `0.051 G^0.1 Re^−0.2`; en büyüğü) kalibre edilir.
* Örtük biçim, ṁ → 0 limitinde denge girdabını kararlı verir; debi arttıkça girdap giriş değerinden dengeye doğru gelişir (Owen'ın türbülans akış parametresi λ_T = C_w/Re_φ^0.8 çıktı olarak raporlanır).
* Rüzgâr ısınması yalnızca rotor torkundan: `W = Ω·T_rotor`, `ΔTt = W/(ṁ·cp + |W|·N/ΔT_max)` (debi sıfıra giderken ΔT_max'a yumuşak doyum).
* Basınç: `p_(i+1) = p_i · exp{ V_m²/(R·Ts,m) · ln(r_(i+1)/r_i) }`.
* "Rotor (eş-dönen)" seçeneğinde iki yüz de döner; debisiz limitte K → 1 (katı cisim).

### 4.7 Sabit debi ve disk pompalama

* `fixedflow`: ṁ kullanıcıdan (ölçülmüş bleed, soğutma ihtiyacı).
* `discpump`: Flow Simulator'daki biçim: `ṁ = C·μ·r·Re^0.8·ζ`, Sultanian: `C = 0.219`, `ζ = (1 − 0.51·Sf)(1 − Sf)^1.6`; Owen & Rogers: `C = 0.1395`, `ζ = |1 − Sf|^1.6`; debi r_b ve r_a değerlerinin farkıdır.

---

## 5. Doğrulama

`python -m pytest -q` ile çalışan testler (tests/test_validation.py):

| Test | Referans | Sonuç |
|---|---|---|
| Tek orifis (boğulmamış/boğulmuş) | izentropik formül | 10⁻¹⁰ bağıl |
| Seri orifisler | doğrudan kök bulma, kütle korunumu | 10⁻⁸ |
| Adyabatik boru | Fanno: f·L/D = F(M1) − F(M2) | %0.2 |
| Boğulmuş boru | debinin arka basınçtan bağımsızlığı | 10⁻⁴ |
| Labirent (Neumann, Cd sabit) | ṁ = Cd·A·√{(p0²−pn²)/(n·R·T)} | 10⁻⁸ |
| Labirent son diş boğulması | debi bağımsızlığı | 10⁻⁶ |
| Zorlanmış/serbest girdap | izentropik kapalı form | 10⁻¹² |
| Kapalı kavite girdabı | K₀ = 0.426 (rotor-stator), 1.0 (eş-dönen) | ±0.002 |
| Dönen radyal boru | Euler işi cp·ΔTt = U2² − U1² | 10⁻⁶ |
| Ön-girdap bağıl sıcaklık | Tt,rel = Tt − U²(2β−1)/(2cp) | 10⁻¹² |
| Enerji (karışım + ısı) | entalpi dengesi | 10⁻⁹ |
| Örnek ağlar | yakınsama, sınır debileri toplamı | 10⁻⁷ |
| K-kaybı (çıkış tanımı), düşük Mach | ṁ = A√{2ρΔp/(1+K)} | 2·10⁻³ |
| Momentum odası, θ = 90° | plenum ile aynı sonuç | 10⁻⁷ |
| Momentum odası, Nart Şekil 5 | Flow Simulator Tablo 1 (aşağıda) | %3.5 / oran %1 |

### 5.1 Flow Simulator karşılaştırması (Nart, Şekil 5 / Tablo 1)

Ağ: K-kaybı elemanları D = 5 mm, 250 mm, 5 mm; K = 2; giriş Pt = Ps = 5 bar, 500 K; çıkış Ps = 2 bar; kuru hava. İkinci eleman θ açısıyla döndürülür. Debi [g/s]:

| θ | Flow Simulator | Nart FlowNet | myFlowNet | M_ex (eleman 2) myFlowNet / FS |
|---|---|---|---|---|
| 0° | 9.395 | 9.389 (−0.06 %) | 9.117 (−2.96 %) | 1.42·10⁻⁴ / 1.50·10⁻⁴ |
| 30° | 9.282 | 9.211 (−0.76 %) | 8.972 (−3.34 %) | 1.42·10⁻⁴ / 1.50·10⁻⁴ |
| 45° | 9.099 | 9.052 (−0.52 %) | 8.839 (−2.85 %) | 1.42·10⁻⁴ / 1.50·10⁻⁴ |
| 60° | 8.948 | 8.906 (−0.47 %) | 8.716 (−2.59 %) | 1.42·10⁻⁴ / 1.50·10⁻⁴ |
| 90° | 8.813 | 8.769 (−0.50 %) | 8.600 (−2.41 %) | 1.42·10⁻⁴ / 1.50·10⁻⁴ |

Açıya bağlı geri kazanım etkisi (θ = 0° / 90° debi oranı) Flow Simulator'da 1.066, myFlowNet'te 1.060'tır; yön modeli doğru çalışıyor. Mutlak seviyedeki −%2.4…−3.3 sapma θ'dan bağımsızdır, yani K-kaybının sıkıştırılabilir uygulamasından gelir: Nart, çıkış Mach sayısından sonra giriş Mach'ının "Miller §7.7'deki gibi" hesaplandığını belirtir; bu adım kitaba bakılmadan birebir üretilemedi. Giriş tanımı aynı ağda +%6.9…+9.3 verir.

---

## 6. Flow Simulator ile kavram eşleşmesi

| Flow Simulator | myFlowNet |
|---|---|
| Plenum / Momentum / Inertial chamber | plenum / momentum / inertial |
| Boundary chamber (TOTPRES/STATPRES, TFIX, XKFIX) | boundary (p_type, T, K) |
| XK (swirl factor), RTR_IDX | K, ref_rotor |
| Orifice (Cd, RPMSEL, DQ_IN, THETA_EX) | orifice (cd, rotor, dq_in, exit_angle) |
| Tube (NACA TN 3150 marching) | pipe |
| Labyrinth Seal Tooth-by-Tooth | labyrinth (tbt) |
| Vortex (free/forced, XK_FWD) | vortex |
| Cavity solver (açısal momentum, regula falsi) | cavity (radyal yürütme, örtük segment çözümü) |
| Disk Pumping | discpump |
| Junction (Miller) | henüz yok – 3-portlu eleman olarak eklenecek |
| Relaxed Newton-Raphson, dW/dP | Newton + çizgi araması, eleman-yerel FD Jacobian |
| K-loss (Miller K, çıkış dinamik basıncı) | kloss, K_def = exit |
| File → Load CAD Model (IGES/STEP), 3B CAD bindirme | File → Load background geometry (STEP/IGES/BREP/STL): meridyen kesiti veya 3B görünüm (§7) |
| Flow from Geometry – Chambers (CAD vertex'lerine oda) | Snap chambers to geometry points (CAD vertex'leri ve kesit köşeleri) |
| Flow from Geometry – Elements (silindirik yüzeyden D, L) | henüz yok – yüz tipi, silindir yarıçapı ve ekseni okunuyor (§8) |

---

## 7. Arka plan CAD geometrisi

Flow Simulator'daki *File → Load CAD Model* özelliğinin karşılığı: ağ, motorun CAD modelinin üzerine çizilir (**File → Load background geometry**, Ctrl+G; sağdaki **Background** paneli; araç çubuğundaki küp düğmesi göster/gizle).

**Dosyalar ve okuyucular.** STEP / IGES / BREP, OpenCASCADE ile okunur ve üçgenlenir: `cadquery-ocp` (önerilen: BRepMesh, gerçek CAD kenarları, yüz tipleri, silindir yarıçap ve eksenleri) ya da yedek olarak `gmsh` (yüzey ağı). STL numpy ile doğrudan okunur; kenarlar dihedral açısı > 30° olan üçgen kenarlarıdır. Yalnız eğri içeren (tel kafes) IGES/STEP çizimleri de desteklenir; kenarlar vektör olarak çizilir. Okuma ayrı bir süreçte yapılır (`python -m myflownet.cad giriş çıkış.npz [kalite]`), sonuç geçici klasörde önbelleğe alınır; büyük ya da bozuk bir dosya editörü kilitlemez. STEP/IGES mm'ye çevrilir; STL için birim panelde seçilir.

**Meridyen çerçevesi.** Motor ekseni **a** (X, Y, Z), referans radyal yön **e₀** ve kesit açısı θ:

    e_r = cos θ · e₀ + sin θ · (a × e₀)      n = a × e_r      q = [a, e_r, n] · (P − O)

q₀ eksenel konum, q₁ kesit düzlemindeki yarıçap, q₂ düzleme dik uzaklıktır. Varsayılan görünümde (yaw = pitch = 0) tuvalin yatay ekseni eksenel, düşey ekseni yarıçaptır: tuval = (oₓ + s·q₀,  o_y − s·q₁), s [px/mm].

**Kesme ve kesit.** *Cut* açıkken q₂ > 0 yarısı (bakana dönük taraf) üçgen düzeyinde kırpılır; *Upper half* q₁ < 0 yarısını da kırpar. Kesit, üçgen ağının q₂ = 0 düzlemiyle kesişimidir: kesilen her üçgen bir doğru parçası verir, parçalar ortak ağ kenarları üzerinden kapalı halkalara zincirlenir (birbirine değen katılar parça kimliğiyle ayrı tutulur) ve çift-tek kuralıyla doldurulur, böylece delikler boş kalır. Düzleme tam düşen düğümler (dönel yüzeylerin dikiş çizgisi) ε kadar kaydırılarak dejenerelik önlenir.

**3B görünüm.** R = Rₓ(pitch) · R_y(yaw) dönmesi, düz gölgeleme I = 0.40 + 0.60·|n·L| ve ressam algoritması (uzaktan yakına; uzun üçgenler en uzun kenarlarından ikiye bölünür). Kesit düzlemi tuvale afin olarak eşlenir: (u, v) = R[0:2, 0:2] · (q₀, q₁). Bu nedenle her görünümde imleç altındaki noktanın (eksenel, r) koordinatı tam hesaplanır; *Network follows the section* açıkken görünüm döndüğünde odalar aynı kesit noktalarında kalacak biçimde aynı afin dönüşümle taşınır (geri alma geçmişi dahil). Gölgeli yüzeyler tuval yakınlaştırmasına göre yeniden çizilen bir raster katmanında, kesit yüzleri ve çevreleri her ölçekte keskin kalan vektör katmanında çizilir.

**Ağ araçları.**

* *Snap chambers to geometry points*: oda taşınırken veya eklenirken kesit düzlemindeki CAD köşe noktalarına ve kesit çevrelerinin köşelerine (yön değişimi > 25°) 11 piksel içinde yakalanır (FS: chambers on vertices).
* *Set chamber radii from background geometry* (Model menüsü / panel): oda referans yarıçapı = |q₁| (seçili odalar, seçim yoksa tümü). Durum çubuğu imlecin eksenel konumunu ve yarıçapını gösterir.
* Yerleşim: ölçek (px/mm), *Fit to network*, *Move / scale on canvas* (sürükle / tekerlek). Bütün ayarlar model dosyasında saklanır; geometri dosya yolu modele göre göreli yazılır.

**Doğruluk.** Kesit konturu üçgenlemeden gelir. θ, dönel modellerin dikiş düzlemine denk geldiğinde (çoğu CAD modelinde θ = 0) yarıçaplar tamdır; aksi halde hata kiriş sapması kadardır (Normal: köşegenin %0.08'i, en çok ~0.3 rad açısal sapma; daha hassas okuma için *Fine*).

Örnek: **Examples → HPT pre-swirl system on CAD geometry** (`examples/geometry/hpt_preswirl_rig.step`, `make_hpt_preswirl_rig.py` ile üretilir).

---

## 8. Sınırlamalar ve geliştirme önerileri

* CAD'den eleman üretimi (Flow Simulator *Flow from Geometry – Elements*): seçilen silindirik yüzeyden çap, uzunluk ve açının elemana aktarılması – yüz tipleri, silindir yarıçapları ve eksenleri okuyucuda hazır.
* 3-kollu T/Y bağlantı elemanı (Miller 1990 diyagramları) – eleman API'si iki portludur; çok portlu eleman ve iç momentum odaları eklenmeli.
* Fırça conta, yatak, gaz yolu-oyuk etkileşimi (rim seal ingestion) modelleri.
* Kavite elemanında cıvata (bolt) sürüklemesi ve duvar ısı transferi; termal ağ (katı sıcaklıkları) bağlaşımı.
* Zamana bağlı (transient) çözüm, haritalı (CFD/test) eleman karakteristikleri, belirsizlik/kalibrasyon araçları.

---

## Kaynaklar

1. Altair Engineering, *Flow Simulator – Solver Technical Manual* (online, help.altair.com/flowsim).
2. Sultanian, B.K. (2018). *Gas Turbines: Internal Flow Systems Modeling*. Cambridge University Press.
3. Owen, J.M., Rogers, R.H. (1989). *Flow and Heat Transfer in Rotating-Disc Systems, Vol. 1: Rotor-Stator Systems*. Research Studies Press.
4. Daily, J.W., Nece, R.E. (1960). Chamber dimension effects on induced flow and frictional resistance of enclosed rotating disks. *ASME J. Basic Eng.* 82, 217–232.
5. von Kármán, T. (1921). Über laminare und turbulente Reibung. *ZAMM* 1 (NACA TM 1092).
6. Shapiro, A.H. (1953). *The Dynamics and Thermodynamics of Compressible Fluid Flow*. Ronald Press.
7. Hubbartt, J.E., Sloan, D.W., Arne, V.L. (1954). NACA TN 3150.
8. McGreehan, W.F., Schotsch, M.J. (1988). Flow characteristics of long orifices with rotation and corner radiusing. *ASME J. Turbomach.* 110, 213–217.
9. Vermes, G. (1961). A fluid mechanics approach to the labyrinth seal leakage problem. *ASME J. Eng. Power* 83, 161–169.
10. Hodkinson, B. (1939). Estimation of the leakage through a labyrinth gland. *Proc. IMechE* 141, 283–288.
11. Martin, H.M. (1908). Labyrinth packings. *Engineering* 85, 35–36.  Egli, A. (1935). The leakage of steam through labyrinth seals. *Trans. ASME* 57, 115–122.
12. Micio, M., Facchini, B., Innocenti, L., Simonetti, F. (2011). Experimental investigation on leakage loss and heat transfer in a straight through labyrinth seal. ASME GT2011-46402.
13. Miller, D.S. (1990). *Internal Flow Systems*, 2nd ed. BHRA.  Idelchik, I.E. *Handbook of Hydraulic Resistance*.
14. Colebrook, C.F. (1939). *J. ICE* 11, 133–156.  Haaland, S.E. (1983). *J. Fluids Eng.* 105, 89–90.  Gnielinski, V. (1975). *Forsch. Ingenieurwes.* 41, 8–16.
15. Majumdar, A.K. – *Generalized Fluid System Simulation Program (GFSSP)*, NASA MSFC.
16. Da Soghe, R., Facchini, B., Innocenti, L., Micio, M. (2011). Analysis of gas turbine rotating cavities by a one-dimensional model. *ASME J. Turbomach.* 133.
17. Nart, Ç. *Development of Newton Raphson Based 1D Flow Network Solver* (TUSAŞ Motor Sanayii, FlowNet; revize taslak R1).
18. Altair Flow Simulator kullanıcı kılavuzu: *Load CAD Model*, *Flow from Geometry – Chambers / Elements* (help.altair.com/flowsim).
19. Open CASCADE Technology (BRepMesh, STEP/IGES çeviricileri); cadquery-ocp Python bağlamaları; Geuzaine, C., Remacle, J.-F. (2009). Gmsh. *Int. J. Numer. Meth. Eng.* 79, 1309–1331.
