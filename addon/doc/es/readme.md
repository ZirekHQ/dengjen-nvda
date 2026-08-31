# Voces neuronales Dengjen para NVDA

> **Aviso sobre el mantenimiento de este fork**
>
> El autor original, Musharraf Omer ([@mush42](https://github.com/mush42)), [anunció en la lista de complementos de NVDA](https://nvda-addons.groups.io/g/nvda-addons/message/27636) que conflictos con contratos comerciales le impiden seguir manteniendo este complemento de código abierto. Este fork continúa el proyecto para mantener el complemento funcionando en las versiones actuales de NVDA, e incluye actualizaciones de compatibilidad junto con correcciones en el administrador de voces y en el controlador del sintetizador. Todo el crédito del trabajo original corresponde a Musharraf Omer.
>
> Esta traducción puede estar desactualizada respecto al [readme en inglés](https://github.com/austek/dengjen-nvda/blob/main/readme.md).
>
> Renombrado de Sonata Neural Voices en la v4.0.0, a petición del autor
> original, como condición para figurar en la Tienda de complementos de NVDA.
> Mismo complemento, mismo mantenedor, misma licencia GPL v2.

Este complemento añade a NVDA voces neuronales de texto a voz. Proporciona un controlador de sintetizador para los modelos de voz de [Piper](https://github.com/rhasspy/piper), que se ejecutan por completo en tu propio equipo, además de un administrador de voces para descargar e instalar voces. Se necesita conexión a internet para descargar voces, pero no para hablar con ellas.

Piper es un sistema de texto a voz rápido, local y neuronal que suena bien y está optimizado para funcionar en dispositivos de gama baja, tales como Raspberry Pi. Puedes escuchar cómo suenan las voces en la página de [muestras de voz de Piper](https://rhasspy.github.io/piper-samples/). La voz se genera con [Sonata](https://github.com/mush42/sonata), un motor Rust multiplataforma para modelos neuronales TTS desarrollado por Musharraf Omer.


# Requisitos

- NVDA 2026.1 o posterior.
- El [Microsoft Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe). El motor de voz incluido en el complemento está compilado con MSVC y no puede iniciarse sin él. Si falta, el complemento muestra un mensaje con ese enlace de descarga; instálalo y reinicia NVDA. La mayoría de los equipos con Windows ya lo tienen.

# Instalación

## Descargando el complemento

Puedes encontrar el paquete de complemento dentro de la sección assets de la [página de release](https://github.com/austek/dengjen-nvda/releases/latest)

## Agregando voces

El complemento es solo un controlador, por lo que no viene con voces por defecto. Necesitarías descargar e instalar las voces que quieras desde el administrador de voces.

Al instalar el complemento y reiniciar NVDA, el complemento te pedirá que descargues e instales al menos una voz, y te dará la opción de abrir el administrador de voces.

También puedes abrir el administrador de voces desde el menú principal de NVDA.

Ten en cuenta que te recomendamos seleccionar las voces con la calidad `low` o `medium` para tu(s) idioma(s) de destino, ya que estas proporcionan un mejor rendimiento. Para un rendimiento adicional, puedes optar por descargar la variante `rápida` de una voz a un costo de calidad de voz ligeramente inferior.

También puedes instalar voces desde archivos locales. Después de obtener el archivo de la voz, abre el administrador de voces, en la pestaña `Instalado`, haz clic en el botón etiquetado como `Instalar desde un archivo local`. Selecciona el archivo de la voz y espera a que la voz se instale.

# Usando el administrador de voces

Abre el administrador de voces desde el menú principal de NVDA, en `Administrador de voces Dengjen...`. Tiene dos pestañas: `Descargar` e `Instalado`.

## Pestaña Descargar

Elige un idioma en la lista `Idioma` para filtrar la lista `Voces disponibles` y después selecciona una voz para actuar sobre ella.

- `Probar` reproduce una muestra corta de la voz seleccionada para que puedas oírla antes de descargarla. La muestra se transmite desde internet y no se instala nada. Mientras se reproduce, ese mismo botón pasa a ser `Detener prueba`.
- `Hablante`, junto al botón de prueba, solo está habilitado para las voces entrenadas con más de un hablante. Selecciona qué hablante se usa en la prueba.
- `Descarga variante estándar` y `Descarga variante rápida` obtienen la voz. Cada botón se deshabilita cuando esa variante ya está instalada, y el de la variante rápida también se deshabilita para las voces que no tienen variante rápida.
- `Refrescar lista de voces` vuelve a obtener el catálogo en lugar de reutilizar la copia guardada durante esta sesión.

## Pestaña Instalado

La lista `Voces instaladas` muestra cada voz instalada con su variante, calidad e idioma.

- `Tarjeta de modelo de la voz...` muestra el archivo `MODEL_CARD` que acompaña a la voz, donde se indica de dónde provienen sus datos de entrenamiento y con qué licencia se distribuyen. No todas las voces incluyen uno.
- `Eliminar voz...` borra la voz seleccionada después de pedirte confirmación. Permanece deshabilitado a menos que tengas al menos dos voces instaladas, y no eliminará la voz que se esté usando en ese momento.
- `Instalar desde un archivo local` instala una voz desde un archivo `.tar.gz` o `.tgz` que ya tengas.

Después de instalar desde un archivo local o de eliminar una voz, el complemento recarga el sintetizador por ti, así que el cambio se aplica de inmediato. Después de una descarga, la voz nueva aparece enseguida en el administrador de voces; si la lista de voces de NVDA todavía no la ha recogido, reinicia NVDA.

# Ajustes de voz

Con `Dengjen Neural Voices` seleccionado como sintetizador, los siguientes ajustes aparecen en los ajustes de voz de NVDA (`menú NVDA` > `Preferencias` > `Opciones` > `Voz`).

`Voz` enumera tus voces instaladas con el formato `nombre (idioma) - calidad`.

`Variante` cambia entre la versión `Standard` y la `Fast` de la voz actual. Solo se enumeran las variantes que realmente tengas instaladas.

`Hablante` se aplica a las voces entrenadas con varios hablantes; en una voz de un solo hablante no tiene efecto. También está disponible en el anillo de ajustes del sintetizador.

`Velocidad`, `Volumen` y `Tono` se comportan como en cualquier otro sintetizador de NVDA. Con `Aumento de velocidad` desactivado, el deslizador de velocidad solo abarca la parte baja del rango de velocidad del motor; al activarlo, el deslizador se reparte por todo el rango, lo que permite una voz mucho más rápida.

## Afinando cómo suena una voz

`Escala de duración`, `Escala de ruido` y `Ruido de anchura` exponen los propios parámetros de inferencia del modelo de Piper. Los tres funcionan igual: el deslizador va de 0 a 100, y 50 significa el valor por defecto con el que se entrenó la voz, por lo que devolver un deslizador a 50 deshace tus cambios en él. De los tres, solo `Escala de duración` se ofrece en el anillo de ajustes del sintetizador.

- `Escala de duración` establece cuánto se mantiene cada sonido del habla. Los valores altos alargan la voz y los bajos la comprimen. Es un mecanismo distinto de `Velocidad` y ambos se combinan, así que lo más sencillo es fijar la rapidez con `Velocidad` y recurrir a este ajuste solo si el ritmo natural de una voz te molesta.
- `Escala de ruido` establece cuánta variación pone el modelo en el tono y la entonación. Los valores altos suenan más expresivos pero menos predecibles.
- `Ruido de anchura` establece cuánto varía la duración de cada sonido del habla, lo que se percibe como ritmo. Los valores altos suenan menos mecánicos pero pueden difuminar la articulación.

Por encima de 50, los deslizadores llegan hasta el doble del valor por defecto de la voz en `Escala de duración`, y hasta el triple en `Escala de ruido` y `Ruido de anchura`. Como 50 siempre significa el valor por defecto de esa voz, una misma posición del deslizador conserva su sentido al cambiar a otra voz.

# Una nota acerca de la calidad de la voz

Las voces actualmente disponibles están entrenadas usando conjuntos de datos para TTS gratuitos que, generalmente, son de baja calidad (en su mayoría audiolibros bajo dominio público o grabaciones de calidad para investigación).

Además, estos conjuntos de datos no son exhaustivos, por lo que algunas voces pueden presentar una pronunciación incorrecta o extraña. Ambos problemas podrían resolverse utilizando mejores conjuntos de datos para el entrenamiento.

Con suerte, el desarrollador de `Piper` y algunos desarrolladores de la comunidad de personas ciegas y con deficiencia visual están trabajando en entrenar mejores voces.

# Solución de problemas

**Dengjen no aparece en la lista de sintetizadores de NVDA, o no se carga.** Las dos causas habituales son que falte el paquete de Visual C++ descrito arriba en Requisitos, y no tener ninguna voz instalada: el controlador se niega deliberadamente a cargarse cuando no encuentra al menos una voz. Abre el administrador de voces desde el menú principal de NVDA, instala una voz y reinicia NVDA.

**Una voz que acabo de descargar no aparece en la lista de voces de NVDA.** Reinicia NVDA. Una descarga actualiza la lista del propio administrador de voces, pero NVDA puede seguir usando el conjunto de voces que cargó al iniciarse.

**Una prueba de voz o la lista de voces falla con un error de conexión.** Ambas se obtienen desde internet. Comprueba tu conexión y después usa `Refrescar lista de voces` en la pestaña Descargar para volver a intentarlo.

**«¡No puedes eliminar la voz actualmente en ejecución!»** Cambia NVDA a otra voz, o a otro sintetizador, y elimínala después.

**La voz tarda en empezar o se corta.** Prefiere las voces de calidad `low` o `medium`, y considera la variante rápida de tu voz. Los modelos de más calidad necesitan bastante más procesamiento por cada frase.

## Reportando problemas

Para cualquier otra cosa, el registro de NVDA suele indicar qué ha fallado: `menú NVDA` > `Herramientas` > `Ver registro`.

Por favor, informa de errores y solicitudes de funciones en el [rastreador de incidencias de este fork](https://github.com/austek/dengjen-nvda/issues), e incluye el registro junto con tu versión de NVDA y la voz que estabas usando.

# Licencia

Copyright(c) 2024, Musharraf Omer. Copyright(c) 2026, Ali Ustek y los colaboradores de este fork. Este software está licenciado bajo la GNU GENERAL PUBLIC LICENSE Version 2 (GPL v2).
