# Voces neuronales Sonata para NVDA

> **Aviso sobre el mantenimiento de este fork**
>
> El autor original, Musharraf Omer ([@mush42](https://github.com/mush42)), [anunció en la lista de complementos de NVDA](https://nvda-addons.groups.io/g/nvda-addons/message/27636) que conflictos con contratos comerciales le impiden seguir manteniendo este complemento de código abierto. Este fork continúa el proyecto para mantener el complemento funcionando en las versiones actuales de NVDA. Todo el crédito del trabajo original corresponde a Musharraf Omer.
>
> Esta traducción puede estar desactualizada respecto al [readme en inglés](https://github.com/austek/sonata-nvda/blob/main/readme.md).

Este complemento implementa un controlador de sintetizador de voz para NVDA usando modelos neuronales TTS. Este soporta [Piper](https://github.com/rhasspy/piper).

[Piper](https://github.com/rhasspy/piper) es un sistema de texto a voz rápido, local y neuronal que suena bien y está optimizado para funcionar en dispositivos de gama baja, tales como Raspberry Pi.

Puedes escuchar las muestras de voz aquí: [Piper voice samples](https://rhasspy.github.io/piper-samples/).

Este complemento utiliza [Sonata: un motor Rust multiplataforma para modelos neuronales TTS](https://github.com/mush42/sonata) el cual está siendo desarrollado por Musharraf Omer.


# Requisitos

- NVDA 2025.1 o posterior (probado hasta 2026.1).
- El [Microsoft Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe). El motor de voz incluido en el complemento está compilado con MSVC y no puede iniciarse sin él. Si falta, el complemento muestra un mensaje con ese enlace de descarga; instálalo y reinicia NVDA. La mayoría de los equipos con Windows ya lo tienen.

# Instalación

## Descargando el complemento

Puedes encontrar el paquete de complemento dentro de la sección assets de la [página de release](https://github.com/austek/sonata-nvda/releases/latest)

## Reportando problemas

Por favor, informa de errores y solicitudes de funciones en el [rastreador de incidencias de este fork](https://github.com/austek/sonata-nvda/issues).

## Agregando voces

El complemento es solo un controlador, por lo que no viene con voces por defecto. Necesitarías descargar e instalar las voces que quieras desde el administrador de voz.

Al instalar el complemento y reiniciar NVDA, el complemento te pedirá que descargues e instales al menos una voz, y te dará la opción de abrir el administrador de voz.

También puedes abrir el administrador de voz desde el menú principal de NVDA.

Ten en cuenta que te recomendamos seleccionar las voces con la calidad  `low` o `medium` para tu(s) idioma(s) de destino, ya que estas proporcionan un mejor rendimiento. Para un rendimiento adicional, puedes optar por descargar la variante `rápida` de una voz a un costo de calidad de voz ligeramente inferior.

También puedes instalar voces de archivos locales. Después de obtener el archivo de voz, abra el administrador de voz, en la pestaña de Instalado, haga clic en el botón etiquetado como `Instalar desde un archivo local`. Selecciona el archivo de voz, espera a que la voz se instale, y reinicia NVDA para refrescar la lista de voces.

## Una nota acerca de la calidad de la voz

Las voces actualmente disponibles están entrenadas usando conjuntos de datos para TTS gratuitos que, generalmente, son de baja calidad (en su mayoría audiolibros bajo dominio público o grabaciones de calidad para investigación).

Agregando que, estos conjuntos de datos no son precisos, por lo que algunas voces pueden presentar una pronunciación incorrecta o extraña. Ambos problemas podrían resolverse utilizando mejores conjuntos de datos para el entrenamiento.

Con suerte, el desarrollador de `Piper` y algunos desarrolladores de la comunidad de personas ciegas y deficiencia visual están trabajando en entrenar mejores voces.

# Licencia

Copyright(c) 2024, Musharraf Omer. Copyright(c) 2026, Ali Ustek y los colaboradores de este fork. Este software está licenciado bajo la GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2).
