# Dengên neuronî yên Sonata ji bo NVDA

> **Danezana lênêrîna vê çapê (fork)**
>
> Nivîskarê resen, Musharraf Omer ([@mush42](https://github.com/mush42)), [di lîsteya pêvekên NVDA de ragihand](https://nvda-addons.groups.io/g/nvda-addons/message/27636) ku nakokiyên peymanên bazirganî nahêlin ku ew lênêrîna vê pêveka çavkaniya vekirî bidomîne. Ev çap projeyê didomîne da ku pêvek li ser guhertoyên heyî yên NVDA-yê bixebite, û nûkirinên lihevhatinê digel serrastkirinên rêveberê dengan û ajokarê sentezkerê dihewîne. Hemû keda xebata resen a Musharraf Omer e.
>
> Dibe ku ev werger li paş [benioku ya îngilîzî](https://github.com/austek/sonata-nvda/blob/main/readme.md) bimîne.

Ev pêvek dengên neuronî yên nivîs-bo-axaftinê li NVDA-yê zêde dike. Ew ajokarekî sentezker ji bo modelên dengî yên [Piper](https://github.com/rhasspy/piper) pêşkêş dike, ku bi tevahî li ser komputera te dixebitin, û digel wê rêveberekî dengan ji bo daxistin û sazkirina dengan. Ji bo daxistina dengan girêdana înternetê pêwîst e, lê ji bo axaftina bi wan na.

Piper pergaleke bilez û herêmî ya neuronî ya nivîs-bo-axaftinê ye ku dengê wê xweş e û ji bo cîhazên kêm-hêz ên wek Raspberry Pi hatiye xweşkirin. Tu dikarî li rûpela [nimûneyên dengên Piper](https://rhasspy.github.io/piper-samples/) guhdarî bikî ka deng çawa ne. Axaftin bi [Sonata](https://github.com/mush42/sonata) tê hilberandin, motoreke Rust a pir-platformî ji bo modelên TTS ên neuronî ku ji aliyê Musharraf Omer ve tê pêşxistin.


# Pêdiviyên pergalê

- NVDA 2025.1 an nûtir (heta 2026.1 hat ceribandin).
- [Microsoft Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe). Motora axaftinê ya ku bi pêvekê re tê, bi MSVC hatiye avakirin û bêyî wê dest pê nake. Ger ew kêm be, pêvek peyamekê nîşan dide ku te ber bi vê daxistinê ve dibe; wê saz bike û NVDA ji nû ve dest pê bike. Li ser piraniya komputerên Windows ew jixwe sazkirî ye.

# Sazkirin

## Daxistina pêvekê

Tu dikarî pakêta pêvekê di beşa assets a [rûpela berdanê](https://github.com/austek/sonata-nvda/releases/latest) de bibînî.

## Zêdekirina dengan

Pêvek tenê ajokarek e, bi xwe re tu dengî nayne. Divê tu dengên ku dixwazî ji rêveberê dengan daxînî û saz bikî.

Piştî sazkirina pêvekê û ji nû ve destpêkirina NVDA-yê, pêvek dê ji te bixwaze ku bi kêmî ve dengekî daxînî û saz bikî, û dê vebijarka vekirina rêveberê dengan pêşkêş bike.

Tu dikarî rêveberê dengan ji pêşeka sereke ya NVDA-yê jî vekî.

Em pêşniyar dikin ku ji bo zimanê xwe yê armanc dengên kalîteya `low` an `medium` hilbijêrî, ji ber ku ew bi gelemperî bersivdayîneke çêtir didin. Ji bo bersivdayîneke hîn bileztir, tu dikarî guhertoya `fast` a dengekî daxînî; lê kalîteya axaftinê hinekî kêmtir dibe.

Tu dikarî dengan ji arşîvên herêmî jî saz bikî. Piştî ku te pelê dengî peyda kir, rêveberê dengan veke, di rûpela `Sazkirî` de li ser bişkoka bi navê `Ji pelê herêmî saz bike` bitikîne. Pelê dengî hilbijêre û li bendê bimîne heta deng saz bibe.

# Bikaranîna rêveberê dengan

Rêveberê dengan ji pêşeka sereke ya NVDA-yê, di `Rêveberê dengên Sonata...` de veke. Du rûpel hene: `Daxistin` û `Sazkirî`.

## Rûpela Daxistin

Ji lîsteya `Ziman` zimanekî hilbijêre da ku lîsteya `Dengên berdest` bêne parzûnkirin, paşê dengê ku dixwazî pê re bixebitî hilbijêre.

- `Pêşdîtin` nimûneyeke kurt a dengê hilbijartî lê dide, wisa ku tu berî daxistinê dikarî guhdarî bikî. Nimûne ji înternetê tê weşandin û tu tişt nayê sazkirin. Dema ku nimûne lê dide, heman bişkok dibe `Pêşdîtinê raweste`.
- `Axêver`, li kêleka bişkoka pêşdîtinê, tenê ji bo dengên ku bi zêdetirî yek axêverî hatine perwerdekirin çalak dibe. Ew hildibijêre ka kîjan axêver di pêşdîtinê de tê bikaranîn.
- `Guhertoya standard daxîne` û `Guhertoya bilez daxîne` dengî tînin. Ger ew guherto jixwe sazkirî be bişkoka wê neçalak dibe, û bişkoka guhertoya bilez ji bo dengên ku guhertoya bilez a wan tune jî neçalak e.
- `Lîsteya dengan nû bike` katalogê ji nû ve tîne, li şûna ku kopyaya vê danişînê ya hilanîn bi kar bîne.

## Rûpela Sazkirî

Lîsteya `Dengên sazkirî` her dengê sazkirî digel guhertoya wî, kalîteya wî û zimanê wî nîşan dide.

- `Karta modela dengî...` pelê `MODEL_CARD` ê ku bi dengî re tê nîşan dide; ew tomar dike ka daneyên perwerdekirinê ji ku hatine û bi çi lîsansê hatine belavkirin. Ne her dengî ev pel heye.
- `Dengî rake...` piştî ku ji te pesendkirinê dixwaze dengê hilbijartî jê dibe. Heta ku bi kêmî ve du deng sazkirî nebin neçalak dimîne, û dengê ku niha tê bikaranîn ranake.
- `Ji pelê herêmî saz bike` dengekî ji arşîveke `.tar.gz` an `.tgz` a ku jixwe li ba te ye saz dike.

Piştî sazkirinê ji arşîveke herêmî an rakirina dengekî, pêvek sentezkerê ji bo te ji nû ve bar dike, loma guhertin yekser dikeve meriyetê. Piştî daxistinekê dengê nû yekser di rêveberê dengan de xuya dibe; ger lîsteya dengan a NVDA-yê hîn wî negirtibe, NVDA ji nû ve dest pê bike.

# Mîhengên dengî

Gava ku `Sonata Neural Voices` wek sentezker hatiye hilbijartin, mîhengên jêrîn di mîhengên axaftinê yên NVDA-yê de xuya dibin (`pêşeka NVDA` > `Bijarte` > `Mîheng` > `Axaftin`).

`Deng` dengên te yên sazkirî bi teşeya `nav (ziman) - kalîte` rêz dike.

`Guherto` di navbera avahiyên `Standard` û `Fast` ên dengê heyî de derbas dibe. Tenê guhertoyên ku bi rastî sazkirî ne tên rêzkirin.

`Axêver` ji bo dengên ku bi gelek axêveran hatine perwerdekirin derbasdar e; li ser dengekî yek-axêver bandor nake. Ew di gera mîhengên sentezker de jî berdest e.

`Lez`, `Deng` û `Bilindahî` wek her sentezkerekî NVDA-yê dixebitin. Gava ku `Zêdekirina lezê` girtî be, xişoka lezê tenê beşa jêrîn a rêza leza motorê digire; gava vekirî be, xişok li tevahiya rêzê belav dibe, ku ev jî rê dide axaftineke pir bileztir.

## Xweşkirina hûrgulî ya dengekî

`Pîvana dirêjahiyê`, `Pîvana xişînê` û `Xişîn w` parametreyên encamdanê yên bi xwe yên modela Piper vedikin. Hersê jî bi heman awayî dixebitin: xişok ji 0 heta 100 diçe, û 50 tê wateya nirxa berdest a ku deng pê hatiye perwerdekirin, loma vegerandina xişokekê bo 50 guhertinên te yên li wê parametreyê vedigerîne. Ji van herseyan tenê `Pîvana dirêjahiyê` di gera mîhengên sentezker de tê pêşkêşkirin.

- `Pîvana dirêjahiyê` diyar dike ka her dengê axaftinê çiqas dirêj tê girtin. Nirxên bilind axaftinê dirêj dikin, nirxên nizm wê teng dikin. Ev ji `Lez` re mekanîzmayeke cuda ye û herdu li hev zêde dibin; loma bi gelemperî hêsantir e ku tu leza xwe bi `Lez` saz bikî û tenê heke tempoya xwezayî ya dengekî te aciz bike xwe bigihînî vê mîhengê.
- `Pîvana xişînê` diyar dike ka model çiqas cûrbecûrî dixe nav tonê û awaza dengî. Nirxên bilind bi awayekî diyarker lê kêmtir pêşbînbar tên bihîstin.
- `Xişîn w` diyar dike ka dirêjahiya dengên axaftinê yên yek bi yek çiqas diguhere, ku ev wek rîtim tê hesîn. Nirxên bilind kêmtir makîneyî tên bihîstin lê dikarin bilêvkirinê tevlihev bikin.

Li jor 50, xişok ji bo `Pîvana dirêjahiyê` heta du qatê nirxa berdest a dengî, û ji bo `Pîvana xişînê` û `Xişîn w` heta sê qatî derdikevin. Ji ber ku 50 her tim tê wateya nirxa berdest a wî dengî, heman cihê xişokê dema ku tu derbasî dengekî din dibî wateya xwe diparêze.

# Têbîniyek li ser kalîteya dengan

Dengên ku niha berdest in bi komên daneyên TTS ên belaş hatine perwerdekirin, ku bi gelemperî kalîteya wan nizm e (bi piranî pirtûkên deng ên di warê giştî de an tomarên bi kalîteya lêkolînê).

Wekî din, ev komên daneyan ne berfireh in, loma dibe ku hin deng bilêvkirineke çewt an ecêb derxînin. Her du pirsgirêk jî bi bikaranîna komên daneyên çêtir ji bo perwerdekirinê çareser dibin.

Bi bextewarî, pêşxistkarê `Piper` û hin pêşxistkarên ji civata kor û kêmbînan li ser perwerdekirina dengên çêtir dixebitin.

# Çareserkirina pirsgirêkan

**Sonata di lîsteya sentezkerên NVDA-yê de tune, an bar nabe.** Du sedemên hevpar ev in: pakêta Visual C++ a ku li jor di beşa Pêdiviyên pergalê de hatiye rave kirin kêm e, an jî tu deng sazkirî nîne — ajokar bi zanetî red dike ku bar bibe gava ku bi kêmî ve dengekî nabîne. Rêveberê dengan ji pêşeka sereke ya NVDA-yê veke, dengekî saz bike, û NVDA ji nû ve dest pê bike.

**Dengê ku min niha daxist di lîsteya dengan a NVDA-yê de nayê pêşkêşkirin.** NVDA ji nû ve dest pê bike. Daxistin lîsteya rêveberê dengan bi xwe nû dike, lê dibe ku NVDA hîn koma dengan a ku li destpêkê bar kiribû bi kar bîne.

**Pêşdîtinek an lîsteya dengan bi çewtiyeke girêdanê bi ser nakeve.** Herdu ji înternetê tên anîn. Girêdana xwe kontrol bike, paşê ji bo ceribandineke nû bişkoka `Lîsteya dengan nû bike` ya di rûpela Daxistin de bi kar bîne.

**«Tu nikarî dengê ku niha çalak e rakî!»** NVDA-yê derbasî dengekî din an sentezkerekî din bike, paşê wî rake.

**Axaftin bi derengî dest pê dike an dibire.** Dengên kalîteya `low` an `medium` bijêre, û guhertoya bilez a dengê xwe bihesibîne. Modelên kalîteya bilindtir ji bo her hevokê bi berçavî hêjmartina zêdetir dixwazin.

## Ragihandina pirsgirêkan

Ji bo her tiştê din, tomara NVDA-yê bi gelemperî dibêje çi çewt çûye: `pêşeka NVDA` > `Amûr` > `Tomarê bibîne`.

Ji kerema xwe çewtiyan û daxwazên taybetmendiyan li [şopînerê pirsgirêkan ê vê çapê](https://github.com/austek/sonata-nvda/issues) ragihîne, û tomarê digel guhertoya NVDA-ya xwe û dengê ku bi kar dianî pê ve bike.

# Lîsans

Copyright(c) 2024, Musharraf Omer. Copyright(c) 2026, Ali Ustek û beşdarên vê çapê. Ev nermalav bi GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2) hatiye lîsanskirin.
