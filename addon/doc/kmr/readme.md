# Dengên neuronî yên Sonata ji bo NVDA

> **Danezana lênêrîna vê çapê (fork)**
>
> Nivîskarê resen, Musharraf Omer ([@mush42](https://github.com/mush42)), [di lîsteya pêvekên NVDA de ragihand](https://nvda-addons.groups.io/g/nvda-addons/message/27636) ku nakokiyên peymanên bazirganî nahêlin ku ew lênêrîna vê pêveka çavkaniya vekirî bidomîne. Ev çap projeyê didomîne da ku pêvek li ser guhertoyên heyî yên NVDA-yê bixebite. Hemû keda xebata resen a Musharraf Omer e.
>
> Dibe ku ev werger li paş [benioku ya îngilîzî](https://github.com/austek/sonata-nvda/blob/main/readme.md) bimîne.

Ev pêvek bi modelên TTS ên neuronî ajokarekî sentezkera axaftinê ji bo NVDA-yê pêk tîne. Ew piştgiriyê dide [Piper](https://github.com/rhasspy/piper).

[Piper](https://github.com/rhasspy/piper) pergaleke bilez û herêmî ya neuronî ya nivîs-bo-axaftinê ye ku dengê wê xweş e û ji bo cîhazên kêm-hêz ên wek Raspberry Pi hatiye xweşkirin.

Tu dikarî nimûneyên dengên Piper li vir guhdarî bikî: [Piper voice samples](https://rhasspy.github.io/piper-samples/).

Ev pêvek [Sonata: motoreke Rust a pir-platformî ji bo modelên TTS ên neuronî](https://github.com/mush42/sonata) bi kar tîne, ku ji aliyê Musharraf Omer ve tê pêşxistin.


# Pêdiviyên pergalê

- NVDA 2025.1 an nûtir (heta 2026.1 hat ceribandin).
- [Microsoft Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe). Motora axaftinê ya ku bi pêvekê re tê, bi MSVC hatiye avakirin û bêyî wê dest pê nake. Ger ew kêm be, pêvek peyamekê nîşan dide ku te ber bi vê daxistinê ve dibe; wê saz bike û NVDA ji nû ve dest pê bike. Li ser piraniya komputerên Windows ew jixwe sazkirî ye.

# Sazkirin

## Daxistina pêvekê

Tu dikarî pakêta pêvekê di beşa assets a [rûpela berdanê](https://github.com/austek/sonata-nvda/releases/latest) de bibînî.

## Ragihandina pirsgirêkan

Ji kerema xwe çewtiyan û daxwazên taybetmendiyan li [şopînerê pirsgirêkan ê vê çapê](https://github.com/austek/sonata-nvda/issues) ragihîne.

## Zêdekirina dengan

Pêvek tenê ajokarek e, bi xwe re tu dengî nayne. Divê tu dengên ku dixwazî ji rêveberê dengan daxînî û saz bikî.

Piştî sazkirina pêvekê û ji nû ve destpêkirina NVDA-yê, pêvek dê ji te bixwaze ku bi kêmî ve dengekî daxînî û saz bikî, û dê vebijarka vekirina rêveberê dengan pêşkêş bike.

Tu dikarî rêveberê dengan ji pêşeka sereke ya NVDA-yê jî vekî.

Em pêşniyar dikin ku ji bo zimanê xwe yê armanc dengên kalîteya `low` an `medium` hilbijêrî, ji ber ku ew bi gelemperî bersivdayîneke çêtir didin. Ji bo bersivdayîneke hîn bileztir, tu dikarî guhertoya `fast` a dengekî daxînî; lê kalîteya axaftinê hinekî kêmtir dibe.

Tu dikarî dengan ji arşîvên herêmî jî saz bikî. Piştî ku te pelê dengî peyda kir, rêveberê dengan veke, di rûpela Sazkirî de li ser bişkoka bi navê `Ji pelê herêmî saz bike` bitikîne. Pelê dengî hilbijêre, li bendê bimîne heta deng saz bibe, û ji bo nûkirina lîsteya dengan NVDA ji nû ve dest pê bike.

## Têbîniyek li ser kalîteya dengan

Dengên ku niha berdest in bi komên daneyên TTS ên belaş hatine perwerdekirin, ku bi gelemperî kalîteya wan nizm e (bi piranî pirtûkên deng ên di warê giştî de an tomarên bi kalîteya lêkolînê).

Wekî din, ev komên daneyan ne berfireh in, loma dibe ku hin deng bilêvkirineke çewt an ecêb derxînin. Her du pirsgirêk jî bi bikaranîna komên daneyên çêtir ji bo perwerdekirinê çareser dibin.

Bi bextewarî, pêşxistkarê `Piper` û hin pêşxistkarên ji civata kor û kêmbînan li ser perwerdekirina dengên çêtir dixebitin.

# Lîsans

Copyright(c) 2024, Musharraf Omer. Copyright(c) 2026, Ali Ustek û beşdarên vê çapê. Ev nermalav bi GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2) hatiye lîsanskirin.
