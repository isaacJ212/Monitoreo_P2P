# 🚀 Binance P2P Arbitrage & Monitor | USDT - NIO (Nicaragua)

Sistema integral de **arbitraje en tiempo real, predicciones horarias matemáticas, cálculo de ganancias netas y alertas inteligentes multicanal (Correo y WhatsApp)** para el comercio de USDT en Córdobas (NIO) de Binance P2P.

Cuenta con una **Interfaz Gráfica Profesional (Crypto Terminal)** servida directamente en tu navegador.

---

## ⚡ Novedades Principales

* ⚡ **Arbitrage Match Maker en Vivo:** Empareja automáticamente el anuncio de compra más barato con el anuncio de venta más caro del mercado, calcula la ganancia neta en Córdobas (C$), el retorno de inversión (% ROI) y busca métodos de pago coincidentes (BAC, LAFISE, Banpro).
* ⏰ **Ventanas Diarias de Arbitraje:** Analiza el histórico por horas (UTC-6 Nicaragua) para determinar exactamente **a qué hora comprar al menor precio** y **a qué hora vender al mayor precio**, calculando el diferencial esperado del día.
* 🧠 **Alertas Inteligentes Automatizadas:**
  * **Arbitrage Match Alert:** Notificación inmediata cuando se detecta un diferencial positivo rentable entre compra y venta.
  * **Compra Barata Inteligente:** Dispara alerta si el precio cae por debajo del promedio histórico reciente o de tu objetivo.
  * **Venta Cara Inteligente:** Dispara alerta si el precio sube por encima del promedio histórico reciente o de tu objetivo.
  * **Multicanal:** Mensajes ejecutivos estructurados vía **Correo Electrónico (SMTP)** y **WhatsApp (Twilio)** con enlaces directos para operar en Binance.
* 🖥️ **Terminal Web de Trading:** Interfaz con diseño Dark Glassmorphism, simulador interactivo de presupuesto, filtros por banco en 1 clic y gráficos de evolución con Chart.js.

---

## 🖥️ Interfaz Gráfica (Terminal Web)

Al arrancar la aplicación, ingresa en tu navegador a:
👉 **[http://localhost:8000/](http://localhost:8000/)**

### Componentes de la Pantalla:
1. **Simulador de Arbitraje (Hero Card):**
   * Muestra la ruta de la operación: *Paso 1 (Compra más barata en NIO) &rarr; USDT obtenidos &rarr; Paso 2 (Venta más cara en NIO)*.
   * Modifica el presupuesto (ej. C$ 2,000, C$ 5,000, C$ 10,000) y observa cómo se recalculan al instante los USDT y la ganancia neta estimada.
   * Enlaces directos a Binance P2P para cada comerciante.
2. **Comparativa vs Promedios Históricos:**
   * Compara los precios actuales en vivo contra la media histórica de la base de datos para saber si estás comprando con descuento o vendiendo con sobreprecio.
3. **Ventana Horaria Óptima de Nicaragua:**
   * Muestra la franja de mayor rentabilidad (ej. Comprar a las 09:00 AM y Vender a las 05:00 PM).
   * Matriz visual de 24 horas con la actividad y horas recomendadas.
4. **Top 10 Anuncios de Compra y Venta:**
   * Compra: Del precio más bajo al más alto.
   * Venta: Del precio más alto al más bajo.
   * Botones de filtrado rápido por banco: `BAC Credomatic`, `Banco LAFISE`, `Banpro / Billetera Móvil`.
5. **Historial de Alertas:**
   * Auditoría de notificaciones enviadas a tu correo o WhatsApp.
6. **Ajuste de Metas:**
   * Modal para cambiar tus precios objetivo de compra y venta en cualquier momento.

---

## 📲 Alertas por Correo y WhatsApp

El sistema de notificaciones está programado para redactar mensajes claros y directos a tu teléfono:

### Ejemplo de Alerta por WhatsApp:
```text
💰 ¡OPORTUNIDAD DE ARBITRAJE USDT/NIO! 🚀
Ganancia Estimada: +C$ 85.00 NIO (+1.70%)
💵 Capital simulado: C$ 5,000 NIO
----------------------------------
🟢 1. COMPRAR USDT BARATO:
• Vendedor: BullandSellCrip
• Precio: C$ 36.80
• Límites: C$ 500 - C$ 6,800
• Bancos: BAC Credomatic Nicaragua

🔴 2. VENDER USDT CARO:
• Comprador: NicaChain
• Precio: C$ 37.45
• Límites: C$ 2,000 - C$ 50,000
• Bancos: BAC Credomatic, Banpro
----------------------------------
🏦 Bancos coincidentes: BAC Credomatic Nicaragua
🔗 P2P Binance: https://p2p.binance.com/es/trade/all-payments/USDT?fiat=NIO
```

---

## 🚀 Despliegue y Ejecución

### Opción 1: Docker Compose (Recomendado)

```bash
# 1. Configurar tus credenciales de correo/WhatsApp
cp .env.example .env

# 2. Levantar el contenedor
docker compose up -d --build

# 3. Ver logs en tiempo real
docker compose logs -f p2p-monitor
```

### Opción 2: Entorno Local (Python)

```bash
# 1. Activar entorno virtual
source .venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Arrancar servidor
fastapi dev main.py
```

Abre en tu navegador: **`http://localhost:8000/`**

---

## 📡 Endpoints de la API

| Método | URI | Descripción |
| :--- | :--- | :--- |
| **`GET`** | `/` | **Terminal Web Dashboard**: Interfaz gráfica completa |
| **`GET`** | `/api/v1/live/{fiat}` | **Mercado en tiempo real**: Anuncios Top 10 ordenados, Match de Arbitraje y comparativas con promedios históricos |
| **`GET`** | `/api/v1/predictions/{fiat}` | **Predicciones & Ventana Horaria**: SMA, Z-Score, proyección 30m/60m y la mejor ventana de arbitraje del día |
| **`GET`** | `/api/v1/history/{fiat}` | **Historial**: Instantáneas almacenadas de compra y venta |
| **`GET`** | `/api/v1/alerts` | **Alertas**: Auditoría de notificaciones despachadas |
| **`GET`** | `/api/v1/config/rules` | **Reglas**: Consulta metas activas y presupuestos |
| **`PUT`** | `/api/v1/config/rules/{fiat}` | **Actualizar Metas**: Modifica objetivos de precio en caliente |
| **`POST`** | `/api/v1/monitor/run` | **Escaneo Manual**: Fuerza la ejecución de un ciclo de análisis |
