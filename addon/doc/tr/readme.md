# NVDA için Sonata sinir ağı sesleri

> **Bakım çatalı bildirimi**
>
> Özgün yazar Musharraf Omer ([@mush42](https://github.com/mush42)), ticari sözleşme çakışmaları nedeniyle bu açık kaynaklı eklentiyi sürdüremeyeceğini [NVDA Eklentileri listesinde duyurdu](https://nvda-addons.groups.io/g/nvda-addons/message/27636). Bu çatal, eklentiyi güncel NVDA sürümlerinde çalışır durumda tutmak için projeyi sürdürüyor. Özgün çalışmanın tüm hakkı Musharraf Omer'e aittir.
>
> Bu çeviri, [İngilizce benioku dosyasının](https://github.com/austek/sonata-nvda/blob/main/readme.md) gerisinde kalmış olabilir.

Bu eklenti, sinir ağı tabanlı TTS modellerini kullanarak NVDA için bir konuşma sentezleyici sürücüsü sağlar. [Piper](https://github.com/rhasspy/piper) desteklenir.

[Piper](https://github.com/rhasspy/piper), kulağa doğal gelen ve Raspberry Pi gibi düşük donanımlı cihazlar için iyileştirilmiş, hızlı ve yerel çalışan bir sinir ağı metin okuma sistemidir.

Piper'ın ses örneklerini buradan dinleyebilirsiniz: [Piper voice samples](https://rhasspy.github.io/piper-samples/).

Bu eklenti, Musharraf Omer tarafından geliştirilen [Sonata: sinir ağı TTS modelleri için platformlar arası bir Rust motoru](https://github.com/mush42/sonata) kullanır.


# Gereksinimler

- NVDA 2025.1 veya sonrası (2026.1 sürümüne kadar sınandı).
- [Microsoft Visual C++ 2015-2022 Yeniden Dağıtılabilir Paketi (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe). Eklentiyle birlikte gelen konuşma motoru MSVC ile derlenmiştir ve bu paket olmadan başlatılamaz. Paket eksikse eklenti sizi bu indirmeye yönlendiren bir ileti gösterir; paketi kurup NVDA'yı yeniden başlatın. Windows çalıştıran çoğu bilgisayarda bu paket zaten kuruludur.

# Kurulum

## Eklentiyi indirme

Eklenti paketini [sürüm sayfasındaki](https://github.com/austek/sonata-nvda/releases/latest) assets bölümünde bulabilirsiniz.

## Sorun bildirme

Lütfen hataları ve özellik isteklerini [bu çatalın sorun izleyicisinde](https://github.com/austek/sonata-nvda/issues) bildirin.

## Ses ekleme

Eklenti yalnızca bir sürücüdür, öntanımlı olarak hiçbir sesle gelmez. İstediğiniz sesleri ses yöneticisinden indirip yüklemeniz gerekir.

Eklentiyi kurup NVDA'yı yeniden başlattığınızda eklenti sizden en az bir ses indirip yüklemenizi ister ve ses yöneticisini açma seçeneği sunar.

Ses yöneticisini NVDA'nın ana menüsünden de açabilirsiniz.

Hedef dil veya dilleriniz için `low` ya da `medium` kalitedeki sesleri seçmenizi öneririz; bunlar genellikle daha iyi yanıt hızı sağlar. Daha da hızlı bir yanıt için bir sesin `fast` sürümünü indirmeyi seçebilirsiniz; bu, konuşma kalitesinde hafif bir düşüşe yol açar.

Sesleri yerel arşivlerden de yükleyebilirsiniz. Ses dosyasını edindikten sonra ses yöneticisini açın, Yüklü sekmesinde `Yerel dosyadan yükle` etiketli düğmeye tıklayın. Ses dosyasını seçin, sesin yüklenmesini bekleyin ve ses listesini tazelemek için NVDA'yı yeniden başlatın.

## Ses kalitesi üzerine bir not

Şu anda kullanılabilen sesler, genellikle düşük kaliteli olan (çoğunlukla kamu malı sesli kitaplar veya araştırma amaçlı kayıtlar) ücretsiz TTS veri kümeleriyle eğitilmiştir.

Ayrıca bu veri kümeleri kapsamlı değildir, bu nedenle bazı sesler hatalı veya tuhaf telaffuzlar üretebilir. Her iki sorun da eğitim için daha iyi veri kümeleri kullanılarak giderilebilir.

Neyse ki `Piper` geliştiricisi ile kör ve az gören topluluğundan bazı geliştiriciler daha iyi sesler eğitmek üzere çalışıyor.

# Lisans

Copyright(c) 2024, Musharraf Omer. Copyright(c) 2026, Ali Ustek ve bu çatalın katkıcıları. Bu yazılım GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2) ile lisanslanmıştır.
