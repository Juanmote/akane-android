# Akane – port para Android

Port no oficial de **Akane** (Ludic Studios, 2018) para consolas y móviles Android (arm64),
con mando físico, controles táctiles, vibración, traducción al castellano, filtros de imagen y más.

**Este repositorio no contiene el juego.** Para jugar necesitas tu propia copia de Akane en Steam.
Cómpralo y apoya a sus creadores: [Steam](https://store.steampowered.com/app/884260/Akane/)

**Versión actual: 1.0**

Port: **Juanmote**. Juego original: **Ludic Studios**. Este proyecto no está afiliado a los autores del juego.

## Versiones del juego que valen

| Copia | Estado |
|---|---|
| **Steam, versión de Windows** | ✅ Probada (es con la que se hizo el port) |
| **Steam, versión de Linux** | ✅ Probada |
| Otras tiendas (GOG, itch.io…), Mac | ❓ Sin probar. La APK avisa si los archivos no coinciden |

## Qué trae el port

### Adaptación a Android
- APK arm64 (Android 7 o superior), horizontal y a pantalla completa.
- Se ajusta a cualquier relación de aspecto, también 4:3 y 8:7 (los menús se ven enteros).
- Límite de FPS: 30, 60 o máximo.
- Partidas y opciones guardadas en la consola (sin Steam).
- Gráficos corregidos para Android (shaders reconstruidos para OpenGL ES 3) y sonido FMOD funcionando.
- Icono propio (normal, redondo y adaptativo).

### Idiomas
- Inglés, **castellano**, portugués e italiano. Se elige en Opciones, en la fila de idioma.

### Mandos físicos (Opciones › MANDO)
- Funciona con el mando integrado de las consolas y con mandos externos.
- Todas las acciones se pueden reasignar (atacar, dash, parry, apuntar, especial, tajo, slayer y reiniciar).
- Vibración en la consola y en el mando (golpes, parry, especial…), con tres intensidades o apagada.

### Controles táctiles (Opciones › MANDO)
- Shuriken como stick flotante en la parte izquierda (al pulsar se iluminan solo las direcciones que tocas),
  botones A, B, X, Y, LB, RB, LT y RT, y pausa arriba en el centro.
- Siguen la configuración del mando: cada botón de la pantalla hace lo mismo que ese botón del mando.
- Modo **automático** (aparecen al tocar la pantalla y se ocultan al usar el mando), siempre o nunca.
- Opacidad (10 %–100 %) y tamaño (60 %–150 %).
- Tocar la pantalla avanza los diálogos y la carga; en el modo adrenalina la mira va donde toques.

### Imagen (Opciones › FILTROS)
- Filtros de pantalla con intensidad ajustable, paletas de color, brillo, contraste, saturación, gamma y viñeta.

### Trucos (Opciones › TRUCOS)
- Invulnerabilidad, aguante infinito, munición infinita y desbloquear todo.

### Créditos
- «PORTED JUANMOTE» en los créditos del juego.

## Instalación

1. Descarga la APK de la última versión en **[Releases](../../releases/latest)** e instálala.
   Si tenías otra versión de Akane para Android firmada con otra clave, desinstálala antes.
2. Copia a la consola la carpeta del juego (la que contiene `Akane_Data`). En Steam:
   clic derecho en Akane › Administrar › Ver archivos locales. Vale la versión de Windows o la de Linux.
   Solo hacen falta `Akane_Data/data.unity3d` y la carpeta `Akane_Data/StreamingAssets`.
3. Abre la app, pulsa **Seleccionar carpeta del juego** y elige esa carpeta (vale también la propia `Akane_Data`).
4. Espera a que se preparen los datos (necesita unos 700 MB libres mientras tanto). Solo se hace la primera vez;
   al actualizar la APK se repite solo.

La APK no lleva gráficos, sonido ni fuentes del juego: los coge de tu copia al prepararlos.
Si tus archivos no coinciden con ninguna de las versiones admitidas, la app avisa.
Después puedes borrar la carpeta copiada.

Registro para diagnosticar fallos: `Android/data/com.juanmote.akane/files/akane_log.txt`.

## Cómo funciona la APK

- Se compila con Unity 2021.3 (IL2CPP, arm64) en modo *split binary*: la APK solo lleva el código y una
  escena de arranque vacía (`AkaneBoot`), y el resto de datos va en una OBB.
- `tools/generica/make_generic.py` convierte esa OBB en un «molde» con todo lo que viene del juego
  (texturas y fuentes) puesto a cero, más un manifiesto por cada versión admitida con las órdenes para
  rellenarlo. Moldes y manifiestos van dentro de la APK (`assets/akane/`).
- Al abrirla, `AkaneSetupActivity` pide la carpeta del juego, reconoce la versión, descomprime
  `data.unity3d` (`AkaneBundle`) y `AkaneObbBuilder` rellena el molde con tus archivos, comprobando cada
  archivo con su CRC. La OBB se guarda en `Android/obb/com.juanmote.akane/`.
- Los bancos de sonido de FMOD (`StreamingAssets/Master Bank*.bank`) se copian tal cual, también comprobados,
  a `Android/data/com.juanmote.akane/files/fmod/`, que es donde los busca el juego.
- Las texturas del juego se compilan con el mismo formato que en PC para que encajen byte a byte con tu copia.

| Archivo | Qué hace |
|---|---|
| `tools/generica/AkaneSetupActivity.java` | Pantalla de arranque: elegir carpeta, reconocer la versión, generar la OBB y copiar el sonido |
| `tools/generica/AkaneObbBuilder.java` | Escribe la OBB a partir del molde, el manifiesto y tus archivos (no depende de Android) |
| `tools/generica/AkaneBundle.java` | Descompresor de bundles UnityFS (LZ4) para leer `data.unity3d` |
| `tools/generica/make_generic.py` | Crea el molde y los manifiestos y comprueba que la OBB se reconstruye igual |
| `tools/generica/gen_texformats.py` | Lista de formatos de textura de PC que se aplican al compilar |
| `tools/generica/ObbTest.java` | Prueba en PC de la reconstrucción, con el mismo código Java que la APK |
| `tools/BuildAndroid.cs` | Script de compilación de Unity (APK completa y genérica) |

El código del port (scripts del juego, shaders reconstruidos, menús, táctil, vibración…) se compila en un
proyecto privado, porque va junto a los datos del juego.

Basado en el sistema de la APK genérica del port de A Short Hike.
