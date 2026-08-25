# Voix neuronales Dengjen pour NVDA

> **Avis de maintenance de ce fork**
>
> L'auteur original, Musharraf Omer ([@mush42](https://github.com/mush42)), [a annoncé sur la liste des extensions NVDA](https://nvda-addons.groups.io/g/nvda-addons/message/27636) que des conflits de contrats commerciaux l'empêchent de continuer à maintenir cette extension open source. Ce fork poursuit le projet afin de garder l'extension fonctionnelle sur les versions actuelles de NVDA, et apporte des mises à jour de compatibilité ainsi que des corrections au gestionnaire de voix et au pilote de synthèse. Tout le mérite du travail original revient à Musharraf Omer.
>
> Cette traduction peut être en retard sur le [readme en anglais](https://github.com/austek/dengjen-nvda/blob/main/readme.md).
>
> Renommée depuis Sonata Neural Voices en v4.0.0, à la demande de l'auteur
> original, comme condition d'inscription au Magasin des extensions NVDA.
> Même extension, même mainteneur, même licence GPL v2.

Cette extension ajoute à NVDA des voix de synthèse vocale neuronales. Elle fournit un pilote de synthèse vocale pour les modèles de voix [Piper](https://github.com/rhasspy/piper), qui fonctionnent entièrement sur votre propre machine, ainsi qu'un gestionnaire de voix pour télécharger et installer des voix. Une connexion internet est nécessaire pour télécharger des voix, mais pas pour parler avec elles.

Piper est un système de synthèse de texte à parole rapide, local et neuronal qui sonne bien et est optimisé pour fonctionner sur des appareils bas de gamme tels que le Raspberry Pi. Vous pouvez écouter le rendu des voix sur la page des [extraits de voix de Piper](https://rhasspy.github.io/piper-samples/). La parole est générée par [Sonata](https://github.com/mush42/sonata), un moteur Rust multiplateforme pour les modèles neuronaux TTS développé par Musharraf Omer.


# Prérequis

- NVDA 2026.1 ou ultérieur.
- Le [Microsoft Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe). Le moteur de synthèse fourni avec l'extension est compilé avec MSVC et ne peut pas démarrer sans lui. S'il est absent, l'extension affiche un message renvoyant vers ce téléchargement ; installez-le puis redémarrez NVDA. La plupart des machines Windows le possèdent déjà.

# Installation

## Téléchargement de l'extension

Vous pouvez trouver le package de l'extension sous la section assets à partir de la [page release](https://github.com/austek/dengjen-nvda/releases/latest)

## Ajout de voix

L'extension n'est qu'un pilote, elle est livrée sans aucune voix par défaut. Vous devez télécharger et installer les voix souhaitées à partir du gestionnaire de voix.

Lors de l'installation de l'extension et du redémarrage de NVDA, l'extension vous demandera de télécharger et d'installer au moins une voix, et vous donnera la possibilité d'ouvrir le gestionnaire de voix.

Vous pouvez également ouvrir le gestionnaire de voix depuis le menu principal de NVDA.

Veuillez noter que nous vous recommandons de choisir des voix de qualité `low` ou `medium` pour votre ou vos langues cibles, car elles offrent généralement une meilleure réactivité. Pour plus de réactivité, vous pouvez choisir de télécharger la variante `rapide` d'une voix au prix d'une qualité vocale légèrement inférieure.

Vous pouvez également installer des voix à partir d'archives locales. Après avoir obtenu le fichier de la voix, ouvrez le gestionnaire de voix, sous l'onglet `Installé`, cliquez sur le bouton intitulé `Installer à partir d'un fichier local`. Choisissez le fichier de la voix et attendez que la voix s'installe.

# Utilisation du gestionnaire de voix

Ouvrez le gestionnaire de voix depuis le menu principal de NVDA, sous `Gestionnaire de voix Dengjen...`. Il comporte deux onglets : `Télécharger` et `Installé`.

## Onglet Télécharger

Choisissez une langue dans la liste `Langue` pour filtrer la liste `Voix disponibles`, puis sélectionnez une voix pour agir sur elle.

- `Aperçu` joue un court extrait de la voix sélectionnée afin que vous puissiez l'entendre avant de la télécharger. L'extrait est diffusé depuis internet et rien n'est installé. Pendant la lecture, ce même bouton devient `Arrêter l'aperçu`.
- `Intervenant`, à côté du bouton d'aperçu, n'est activé que pour les voix entraînées avec plusieurs intervenants. Il choisit l'intervenant utilisé pour l'aperçu.
- `Télécharger la variante standard` et `Télécharger une variante rapide` récupèrent la voix. Chaque bouton est désactivé lorsque cette variante est déjà installée, et celui de la variante rapide est également désactivé pour les voix qui n'en possèdent pas.
- `Rafraîchir la liste des voix` récupère à nouveau le catalogue au lieu de réutiliser la copie mise en cache pour cette session.

## Onglet Installé

La liste `Voix installées` affiche chaque voix installée avec sa variante, sa qualité et sa langue.

- `Fiche du modèle de la voix...` affiche le fichier `MODEL_CARD` livré avec la voix, qui indique la provenance de ses données d'entraînement et sa licence. Toutes les voix n'en contiennent pas.
- `Supprimer la voix...` supprime la voix sélectionnée après vous avoir demandé confirmation. Ce bouton reste désactivé tant que vous n'avez pas au moins deux voix installées, et il ne supprimera pas la voix en cours d'utilisation.
- `Installer à partir d'un fichier local` installe une voix depuis une archive `.tar.gz` ou `.tgz` que vous possédez déjà.

Après une installation à partir d'une archive locale ou la suppression d'une voix, l'extension recharge le synthétiseur pour vous, le changement s'applique donc immédiatement. Après un téléchargement, la nouvelle voix apparaît aussitôt dans le gestionnaire de voix ; si la liste des voix de NVDA ne l'a pas encore prise en compte, redémarrez NVDA.

# Paramètres de la voix

Avec `Dengjen Neural Voices` sélectionné comme synthétiseur, les paramètres suivants apparaissent dans les paramètres de parole de NVDA (`menu NVDA` > `Préférences` > `Paramètres` > `Parole`).

`Voix` énumère vos voix installées sous la forme `nom (langue) - qualité`.

`Variante` bascule entre la version `Standard` et la version `Fast` de la voix actuelle. Seules les variantes que vous avez réellement installées sont proposées.

`Intervenant` s'applique aux voix entraînées avec plusieurs intervenants ; sur une voix à intervenant unique, il n'a aucun effet. Il est également disponible dans le cercle des paramètres du synthétiseur.

`Vitesse`, `Volume` et `Hauteur` se comportent comme pour n'importe quel synthétiseur de NVDA. Lorsque `Augmentation de vitesse` est désactivée, le curseur de vitesse ne couvre que la partie basse de la plage de vitesse du moteur ; en l'activant, le curseur se répartit sur toute la plage, ce qui permet une parole beaucoup plus rapide.

## Réglage fin du rendu d'une voix

`Échelle de durée`, `Échelle de bruit` et `Hauteur de bruit` exposent les paramètres d'inférence propres au modèle Piper. Tous trois fonctionnent de la même manière : le curseur va de 0 à 100, et 50 correspond à la valeur par défaut avec laquelle la voix a été entraînée, si bien que ramener un curseur à 50 annule vos modifications. Parmi les trois, seule `Échelle de durée` est proposée dans le cercle des paramètres du synthétiseur.

- `Échelle de durée` définit la durée pendant laquelle chaque son de parole est tenu. Les valeurs élevées étirent la parole, les valeurs faibles la compriment. C'est un mécanisme distinct de `Vitesse` et les deux se combinent : il est donc généralement plus simple de régler votre rapidité avec `Vitesse` et de ne recourir à ce paramètre que si le rythme naturel d'une voix vous dérange.
- `Échelle de bruit` définit l'ampleur de la variation que le modèle introduit dans le timbre et l'intonation. Les valeurs élevées sonnent plus expressives mais moins prévisibles.
- `Hauteur de bruit` définit l'ampleur de la variation de durée des sons de parole individuels, ce qui se perçoit comme du rythme. Les valeurs élevées sonnent moins mécaniques mais peuvent brouiller l'articulation.

Au-delà de 50, les curseurs montent jusqu'au double de la valeur par défaut de la voix pour `Échelle de durée`, et jusqu'au triple pour `Échelle de bruit` et `Hauteur de bruit`. Comme 50 signifie toujours la valeur par défaut de cette voix, une même position du curseur garde son sens lorsque vous passez à une autre voix.

# Une note sur la qualité de la voix

Les voix actuellement disponibles sont formées à l'aide d'ensembles de données TTS disponibles gratuitement, qui sont généralement de mauvaise qualité (principalement des livres audio du domaine public ou des enregistrements de qualité de recherche).

De plus, ces ensembles de données ne sont pas exhaustifs, c'est pourquoi certaines voix peuvent présenter une prononciation incorrecte ou étrange. Les deux problèmes pourraient être résolus en utilisant de meilleurs ensembles de données pour la formation.

Heureusement, le développeur de `Piper` et certains développeurs de la communauté des aveugles et des malvoyants travaillent à la formation de meilleures voix.

# Dépannage

**Dengjen est absent de la liste des synthétiseurs de NVDA, ou ne se charge pas.** Les deux causes habituelles sont l'absence du redistribuable Visual C++ décrit plus haut dans Prérequis, et le fait de n'avoir aucune voix installée : le pilote refuse délibérément de se charger lorsqu'il ne trouve pas au moins une voix. Ouvrez le gestionnaire de voix depuis le menu principal de NVDA, installez une voix, puis redémarrez NVDA.

**Une voix que je viens de télécharger n'est pas proposée dans la liste des voix de NVDA.** Redémarrez NVDA. Un téléchargement rafraîchit la liste du gestionnaire de voix lui-même, mais NVDA peut encore utiliser le jeu de voix chargé à son démarrage.

**Un aperçu ou la liste des voix échoue avec une erreur de connexion.** Les deux sont récupérés depuis internet. Vérifiez votre connexion, puis utilisez `Rafraîchir la liste des voix` dans l'onglet Télécharger pour réessayer.

**« Vous ne pouvez pas supprimer la voix en cours d'exécution ! »** Basculez NVDA sur une autre voix, ou sur un autre synthétiseur, puis supprimez-la.

**La parole démarre lentement ou hache.** Préférez les voix de qualité `low` ou `medium`, et envisagez la variante rapide de votre voix. Les modèles de qualité supérieure demandent nettement plus de traitement par énoncé.

## Signaler des problèmes

Pour tout le reste, le journal de NVDA indique généralement ce qui a échoué : `menu NVDA` > `Outils` > `Voir le journal`.

Merci de signaler les bogues et les demandes de fonctionnalités sur le [gestionnaire de tickets de ce fork](https://github.com/austek/dengjen-nvda/issues), en y joignant le journal ainsi que votre version de NVDA et la voix que vous utilisiez.

# Licence

Copyright(c) 2024, Musharraf Omer. Copyright(c) 2026, Ali Ustek et les contributeurs de ce fork. Ce logiciel est sous licence GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2).
