# NVDA için Sonata sinir ağı sesleri

> **Bakım çatalı bildirimi**
>
> Özgün yazar Musharraf Omer ([@mush42](https://github.com/mush42)), ticari sözleşme çakışmaları nedeniyle bu açık kaynaklı eklentiyi sürdüremeyeceğini [NVDA Eklentileri listesinde duyurdu](https://nvda-addons.groups.io/g/nvda-addons/message/27636). Bu çatal, eklentiyi güncel NVDA sürümlerinde çalışır durumda tutmak için projeyi sürdürüyor; uyumluluk güncellemelerinin yanı sıra ses yöneticisi ve sentezleyici sürücüsündeki düzeltmeleri de içerir. Özgün çalışmanın tüm hakkı Musharraf Omer'e aittir.
>
> Bu çeviri, [İngilizce benioku dosyasının](https://github.com/austek/sonata-nvda/blob/main/readme.md) gerisinde kalmış olabilir.

Bu eklenti NVDA'ya sinir ağı tabanlı metin okuma sesleri ekler. Tamamen kendi bilgisayarınızda çalışan [Piper](https://github.com/rhasspy/piper) ses modelleri için bir sentezleyici sürücüsünün yanı sıra, sesleri indirip yüklemeye yarayan bir ses yöneticisi sağlar. Sesleri indirmek için internet bağlantısı gerekir, ancak onlarla konuşmak için gerekmez.

Piper, kulağa doğal gelen ve Raspberry Pi gibi düşük donanımlı cihazlar için iyileştirilmiş, hızlı ve yerel çalışan bir sinir ağı metin okuma sistemidir. Seslerin nasıl olduğunu [Piper ses örnekleri](https://rhasspy.github.io/piper-samples/) sayfasından dinleyebilirsiniz. Konuşma, Musharraf Omer tarafından geliştirilen [Sonata](https://github.com/mush42/sonata) ile üretilir; bu, sinir ağı TTS modelleri için platformlar arası bir Rust motorudur.


# Gereksinimler

- NVDA 2025.1 veya sonrası (2026.1 sürümüne kadar sınandı).
- [Microsoft Visual C++ 2015-2022 Yeniden Dağıtılabilir Paketi (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe). Eklentiyle birlikte gelen konuşma motoru MSVC ile derlenmiştir ve bu paket olmadan başlatılamaz. Paket eksikse eklenti sizi bu indirmeye yönlendiren bir ileti gösterir; paketi kurup NVDA'yı yeniden başlatın. Windows çalıştıran çoğu bilgisayarda bu paket zaten kuruludur.

# Kurulum

## Eklentiyi indirme

Eklenti paketini [sürüm sayfasındaki](https://github.com/austek/sonata-nvda/releases/latest) assets bölümünde bulabilirsiniz.

## Ses ekleme

Eklenti yalnızca bir sürücüdür, öntanımlı olarak hiçbir sesle gelmez. İstediğiniz sesleri ses yöneticisinden indirip yüklemeniz gerekir.

Eklentiyi kurup NVDA'yı yeniden başlattığınızda eklenti sizden en az bir ses indirip yüklemenizi ister ve ses yöneticisini açma seçeneği sunar.

Ses yöneticisini NVDA'nın ana menüsünden de açabilirsiniz.

Hedef dil veya dilleriniz için `low` ya da `medium` kalitedeki sesleri seçmenizi öneririz; bunlar genellikle daha iyi yanıt hızı sağlar. Daha da hızlı bir yanıt için bir sesin `fast` sürümünü indirmeyi seçebilirsiniz; bu, konuşma kalitesinde hafif bir düşüşe yol açar.

Sesleri yerel arşivlerden de yükleyebilirsiniz. Ses dosyasını edindikten sonra ses yöneticisini açın, `Yüklü` sekmesinde `Yerel dosyadan yükle` etiketli düğmeye tıklayın. Ses dosyasını seçin ve sesin yüklenmesini bekleyin.

# Ses yöneticisini kullanma

Ses yöneticisini NVDA'nın ana menüsünden, `Sonata ses yöneticisi...` altından açın. İki sekmesi vardır: `İndir` ve `Yüklü`.

## İndir sekmesi

`Kullanılabilir sesler` listesini süzmek için `Dil` listesinden bir dil seçin, ardından üzerinde işlem yapmak istediğiniz sesi seçin.

- `Önizle`, seçili sesin kısa bir örneğini çalar; böylece indirmeden önce dinleyebilirsiniz. Örnek internetten akıtılır ve hiçbir şey yüklenmez. Örnek çalarken aynı düğme `Önizlemeyi durdur` olur.
- Önizleme düğmesinin yanındaki `Konuşmacı`, yalnızca birden çok konuşmacıyla eğitilmiş sesler için etkinleşir. Önizlemede hangi konuşmacının kullanılacağını seçer.
- `Standart sürümü indir` ve `Hızlı sürümü indir` sesi getirir. İlgili sürüm zaten yüklüyse düğmesi devre dışı kalır; hızlı sürüm düğmesi, hızlı sürümü olmayan sesler için de devre dışıdır.
- `Ses listesini yenile`, bu oturum için önbelleğe alınan kopyayı kullanmak yerine kataloğu yeniden getirir.

## Yüklü sekmesi

`Yüklü sesler` listesi, yüklü her sesi sürümü, kalitesi ve diliyle birlikte gösterir.

- `Ses model kartı...`, sesle birlikte gelen `MODEL_CARD` dosyasını gösterir; bu dosya eğitim verilerinin nereden geldiğini ve nasıl lisanslandığını belirtir. Her sesin bu dosyası bulunmaz.
- `Sesi kaldır...`, onayınızı istedikten sonra seçili sesi siler. En az iki ses yüklü olmadıkça devre dışı kalır ve o anda kullanılan sesi kaldırmaz.
- `Yerel dosyadan yükle`, elinizde bulunan bir `.tar.gz` ya da `.tgz` arşivinden ses yükler.

Yerel bir arşivden yükleme yaptıktan ya da bir sesi kaldırdıktan sonra eklenti sentezleyiciyi sizin için yeniden yükler, bu yüzden değişiklik hemen geçerli olur. Bir indirmenin ardından yeni ses ses yöneticisinde hemen görünür; NVDA'nın kendi ses listesi sesi henüz almadıysa NVDA'yı yeniden başlatın.

# Ses ayarları

Sentezleyici olarak `Sonata Neural Voices` seçiliyken aşağıdaki ayarlar NVDA'nın konuşma ayarlarında görünür (`NVDA menüsü` > `Tercihler` > `Ayarlar` > `Konuşma`).

`Ses`, yüklü seslerinizi `ad (dil) - kalite` biçiminde listeler.

`Sürüm`, geçerli sesin `Standard` ve `Fast` yapıları arasında geçiş yapar. Yalnızca gerçekten yüklü olan sürümler listelenir.

`Konuşmacı`, birden çok konuşmacıyla eğitilmiş sesler için geçerlidir; tek konuşmacılı bir seste etkisi yoktur. Sentezleyici ayarlar halkasında da bulunur.

`Hız`, `Ses düzeyi` ve `Perde`, NVDA'nın diğer sentezleyicilerinde olduğu gibi davranır. `Hız artırma` kapalıyken hız kaydırıcısı motorun hız aralığının yalnızca alt bölümünü kapsar; açıldığında kaydırıcı tüm aralığa yayılır ve bu da çok daha hızlı konuşmaya olanak verir.

## Bir sesin tonunu ince ayarlama

`Uzunluk ölçeği`, `Gürültü ölçeği` ve `Gürültü w`, Piper modelinin kendi çıkarım değiştirgelerini açığa çıkarır. Üçü de aynı biçimde çalışır: kaydırıcı 0 ile 100 arasındadır ve 50, sesin eğitildiği öntanımlı değer anlamına gelir; bu yüzden bir kaydırıcıyı 50'ye döndürmek o değiştirgedeki değişikliklerinizi geri alır. Üçünden yalnızca `Uzunluk ölçeği` sentezleyici ayarlar halkasında sunulur.

- `Uzunluk ölçeği`, her konuşma sesinin ne kadar süre tutulacağını belirler. Yüksek değerler konuşmayı uzatır, düşük değerler sıkıştırır. Bu, `Hız`dan ayrı bir düzenektir ve ikisi birleşir; bu nedenle hızınızı `Hız` ile ayarlayıp, yalnızca bir sesin doğal temposu sizi rahatsız ediyorsa bu ayara başvurmak genellikle en kolayıdır.
- `Gürültü ölçeği`, modelin tona ve ezgiye ne kadar değişkenlik katacağını belirler. Yüksek değerler daha anlatımlı ama daha az öngörülebilir duyulur.
- `Gürültü w`, tek tek konuşma seslerinin süresinin ne kadar değiştiğini belirler; bu da tartım olarak algılanır. Yüksek değerler daha az makinemsi duyulur ama boğumlamayı bulanıklaştırabilir.

50'nin üzerinde kaydırıcılar `Uzunluk ölçeği` için sesin öntanımlı değerinin iki katına, `Gürültü ölçeği` ve `Gürültü w` için üç katına kadar çıkar. 50 her zaman o sesin öntanımlı değeri anlamına geldiğinden, aynı kaydırıcı konumu başka bir sese geçtiğinizde anlamını korur.

# Ses kalitesi üzerine bir not

Şu anda kullanılabilen sesler, genellikle düşük kaliteli olan (çoğunlukla kamu malı sesli kitaplar veya araştırma amaçlı kayıtlar) ücretsiz TTS veri kümeleriyle eğitilmiştir.

Ayrıca bu veri kümeleri kapsamlı değildir, bu nedenle bazı sesler hatalı veya tuhaf telaffuzlar üretebilir. Her iki sorun da eğitim için daha iyi veri kümeleri kullanılarak giderilebilir.

Neyse ki `Piper` geliştiricisi ile kör ve az gören topluluğundan bazı geliştiriciler daha iyi sesler eğitmek üzere çalışıyor.

# Sorun giderme

**Sonata, NVDA'nın sentezleyici listesinde yok ya da yüklenmiyor.** Bunun iki olağan nedeni, yukarıda Gereksinimler bölümünde anlatılan Visual C++ paketinin eksik olması ve hiç ses yüklü olmamasıdır: sürücü, en az bir ses bulamadığında bilinçli olarak yüklenmeyi reddeder. NVDA'nın ana menüsünden ses yöneticisini açın, bir ses yükleyin ve NVDA'yı yeniden başlatın.

**Yeni indirdiğim bir ses NVDA'nın ses listesinde sunulmuyor.** NVDA'yı yeniden başlatın. İndirme, ses yöneticisinin kendi listesini tazeler, ancak NVDA hâlâ başlangıçta yüklediği ses kümesini kullanıyor olabilir.

**Bir önizleme ya da ses listesi bağlantı hatasıyla başarısız oluyor.** İkisi de internetten getirilir. Bağlantınızı denetleyin, ardından yeniden denemek için İndir sekmesindeki `Ses listesini yenile` düğmesini kullanın.

**"Şu anda etkin olan sesi kaldıramazsınız!"** NVDA'yı başka bir sese ya da başka bir sentezleyiciye geçirin, sonra sesi kaldırın.

**Konuşma geç başlıyor ya da kesiliyor.** `low` ya da `medium` kalitedeki sesleri yeğleyin ve sesinizin hızlı sürümünü değerlendirin. Daha yüksek kaliteli modeller her sözce için belirgin biçimde daha çok işlem gerektirir.

## Sorun bildirme

Bunların dışındaki durumlarda NVDA'nın günlüğü genellikle neyin ters gittiğini söyler: `NVDA menüsü` > `Araçlar` > `Günlüğü görüntüle`.

Lütfen hataları ve özellik isteklerini [bu çatalın sorun izleyicisinde](https://github.com/austek/sonata-nvda/issues) bildirin; günlüğü, NVDA sürümünüzü ve kullandığınız sesi de ekleyin.

# Lisans

Copyright(c) 2024, Musharraf Omer. Copyright(c) 2026, Ali Ustek ve bu çatalın katkıcıları. Bu yazılım GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2) ile lisanslanmıştır.
