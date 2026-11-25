# 🚀 Monitor P2P Binance: USDT / NIO (Nicaragua)

Aplicación web y API para **consultar el comercio P2P de Binance en tiempo real**, detectar **compras baratas** y **ventas caras**, hacer **predicciones de precios y horarios óptimos**, y recibir **alertas automáticas en tu Correo o WhatsApp**.

Cuenta con una **Interfaz Gráfica (Dashboard Web)** lista para usar en tu navegador.

---

## 🧭 ¿Qué hace esta aplicación exactamente?

En Nicaragua, el comercio de **USDT** contra **Córdobas (NIO)** en Binance P2P varía constantemente. Esta app te ayuda a:

1. **Ver precios y anuncios en tiempo real:**
   * Lista los anuncios activos con sus **límites mínimos y máximos en córdobas** (ej. Mínimo C$500 - Máximo C$10,000), el comerciante, su % de órdenes completadas y los **métodos de pago** (BAC Credomatic, Banco LAFISE, Billetera Móvil Banpro, etc.).
2. **Alertarte automáticamente (Notificaciones Push):**
   * **Compra Barata (BUY):** Cuando alguien venda USDT a un precio menor o igual a tu objetivo (ejemplo: si baja a C$36.80 o menos), te envía una alerta para que compres barato.
   * **Venta Cara (SELL):** Cuando alguien compre USDT a un precio mayor o igual a tu objetivo (ejemplo: si sube a C$38.00 o más), te envía una alerta para que vendas con ganancia.
   * Llega a tu **Correo Gmail** o a tu **WhatsApp / SMS (Twilio)**.
3. **Predicciones y Horarios Óptimos en Nicaragua:**
   * Basado en el historial recolectado, calcula **a qué horas del día el precio suele ser más barato para comprar** y **a qué horas del día suele pagarse mejor para vender**.
   * Estima proyecciones a **+30 minutos** y **+60 minutos** con regresión lineal y calcula la tendencia (`ALCISTA`, `BAJISTA` o `LATERAL`).
4. **Dashboard Gráfico Web:**
   * Entras desde tu navegador a `http://localhost:8000/` y ves todo en vivo: gráficos interactivos, tablas de comerciantes, mejores horas del día y un botón para cambiar tus objetivos de precio con un clic.

---

## ❓ ¿Por qué a veces un endpoint parecía "no retornar nada"?

Si al probar los endpoints en tu navegador viste pantallas vacías o resultados con `[]`:
* **`http://localhost:8000/`**: Antes no tenía interfaz visual; ahora ya tiene el **Dashboard Web interactivo completo**.
* **`/api/v1/alerts`**: Devuelve `[]` (lista vacía) si **aún no se ha disparado ninguna alerta**. Es decir, si el precio de mercado no ha tocado tu meta de compra barata ni de venta cara, no hay alertas en el registro.
* **`/api/v1/history/NIO`**: Si la base de datos acaba de crearse, solo tendrá registros después de que el temporizador haga su primera lectura o cuando pulses el botón **"Escanear Ahora"**.
* **`/api/v1/live/NIO`**: Este **siempre devuelve datos frescos de Binance al segundo**.

---

## 🖥️ Interfaz Gráfica (Dashboard Web)

Al arrancar el proyecto, abre en tu navegador:
👉 **[http://localhost:8000/](http://localhost:8000/)**

### ¿Qué encuentras en la pantalla?
1. **Tarjetas de Mercado en Vivo:**
   * Mejor precio de Compra y Venta en Córdobas (NIO) por cada USDT.
   * Margen de ganancia o *Spread* en C$ y en porcentaje.
   * Nombre del comerciante, si está verificado (✓) y sus límites en córdobas.
2. **Predicción Matemática y Horarios Recomendados:**
   * **Horas ideales para COMPRAR barato** (ej. 09:00 AM, 02:00 PM hora de Nicaragua).
   * **Horas ideales para VENDER caro** (ej. 03:00 PM, 06:00 PM).
   * Métodos de pago más activos y límites promedio de cada banco.
   * Proyecciones de precio a +30 min y +60 min.
3. **Gráfica Interactiva (Chart.js):**
   * Curva histórica de evolución de precios de compra vs venta.
4. **Libro de Anuncios P2P Detallado:**
   * Tablas separadas para Compras y Ventas con montos mínimos, montos máximos y etiquetas de bancos.
5. **Configuración de Objetivos con un Clic:**
   * Botón **"Objetivos"** para cambiar el precio al que quieres que te avise sin tener que tocar código ni reiniciar la aplicación.
6. **Botón "Escanear Ahora":**
   * Fuerza una consulta inmediata y guarda la foto en el histórico.

---

## ⚡ Inicio Rápido (Cómo levantarlo)

### Con Docker Compose (La forma más fácil)

1. **Configura tu archivo de variables:**
   ```bash
   cp .env.example .env
   ```
   *(Si deseas alertas por correo o WhatsApp, edita tu `.env` con tus datos).*

2. **Iniciar la aplicación:**
   ```bash
   docker compose up -d --build
   ```

3. **Abrir en tu navegador:**
   Entra a [http://localhost:8000/](http://localhost:8000/)

4. **Para detenerlo:**
   ```bash
   docker compose down
   ```

---

### En tu computadora local (con Python)

1. **Crear y activar entorno virtual:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Instalar librerías:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Arrancar el servidor:**
   ```bash
   fastapi dev main.py
   ```
   *(o también: `uvicorn main:app --reload`)*

---

## 📡 Lista de URIs y Endpoints (Documentación Simple)

Todos los endpoints responden en formato JSON.

### 1. `GET /` &rarr; Dashboard Gráfico Web
Abre la interfaz visual completa en tu navegador.

---

### 2. `GET /api/v1/live/NIO` &rarr; Datos en Vivo al Instante
Consulta Binance P2P directamente en ese segundo.
* **Parámetros opcionales:**
  * `budget`: tu presupuesto en córdobas (defecto: `5000`).
  * `only_merchants`: `true` si solo quieres comerciantes verificados con insignia.
* **Ejemplo cURL:**
  ```bash
  curl -s "http://localhost:8000/api/v1/live/NIO?budget=3000"
  ```
* **Respuesta:**
  ```json
  {
    "fiat": "NIO",
    "asset": "USDT",
    "checked_at": "2026-11-24T21:00:00Z",
    "best_buy": {
      "price": 37.04,
      "merchant_name": "BullandSellCrip",
      "min_limit": 293.0,
      "max_limit": 6800.0,
      "suggested_amount_fiat": 3000.0,
      "payment_methods": ["BAC Credomatic Nicaragua"],
      "finish_rate_pct": 96.2
    },
    "best_sell": {
      "price": 36.61,
      "merchant_name": "NicaChain",
      "min_limit": 9000.0,
      "max_limit": 350000.0,
      "payment_methods": ["Banco Lafise Nicaragua", "Billetera Movil Banpro"]
    },
    "buy_ads": [ /* Lista con los 10 mejores anuncios */ ],
    "sell_ads": [ /* Lista con los 10 mejores anuncios */ ]
  }
  ```

---

### 3. `GET /api/v1/predictions/NIO` &rarr; Predicciones y Horarios Óptimos
Devuelve las mejores horas para comprar o vender y las proyecciones a 30 y 60 minutos.
* **Ejemplo cURL:**
  ```bash
  curl -s "http://localhost:8000/api/v1/predictions/NIO"
  ```
* **Respuesta:**
  ```json
  {
    "fiat": "NIO",
    "asset": "USDT",
    "buy_analysis": {
      "trend": "LATERAL",
      "z_score": 0.0,
      "projected_next_30m": 37.04,
      "projected_next_60m": 37.04,
      "recommendation": "NEUTRAL: Precio dentro del rango normal."
    },
    "time_patterns": {
      "best_hours_to_buy": ["02:00 PM", "09:00 AM"],
      "best_hours_to_sell": ["03:00 PM", "06:00 PM"],
      "popular_payment_methods": [
        {
          "method": "BAC Credomatic Nicaragua",
          "frequency": 24,
          "avg_min_limit": 1500.0,
          "avg_max_limit": 50000.0
        }
      ],
      "summary_insight": "Mejores horas para COMPRAR barato: 02:00 PM, 09:00 AM. Método más activo: BAC Credomatic."
    }
  }
  ```

---

### 4. `GET /api/v1/history/NIO` &rarr; Historial Guardado
Devuelve las instantáneas guardadas para graficar o analizar.
* **Parámetros:** `trade_type=BUY` o `trade_type=SELL`, `limit=50`.
* **Ejemplo:** `http://localhost:8000/api/v1/history/NIO?trade_type=BUY&limit=20`

---

### 5. `GET /api/v1/alerts` &rarr; Historial de Alertas Despachadas
Muestra los registros de avisos que se enviaron por correo o WhatsApp.
* **Ejemplo:** `http://localhost:8000/api/v1/alerts?limit=10`

---

### 6. `PUT /api/v1/config/rules/NIO` &rarr; Cambiar tus Metas de Alerta
Cambia el precio de compra o venta en el que quieres ser notificado:
* **Ejemplo:**
  ```bash
  curl -X PUT "http://localhost:8000/api/v1/config/rules/NIO" \
    -H "Content-Type: application/json" \
    -d '{
      "buy_target": 36.80,
      "sell_target": 38.50,
      "budget": 2000.0,
      "enabled": true
    }'
  ```

---

### 7. `POST /api/v1/monitor/run` &rarr; Forzar Escaneo Inmediato
Ejecuta la revisión en el momento exacto sin esperar al programador de fondo.

---

## 🛠️ Configuración de Alertas (.env)

| Variable | ¿Para qué sirve? | Ejemplo |
| :--- | :--- | :--- |
| `POLL_INTERVAL_MINUTES` | Cada cuántos minutos revisa el mercado solo | `3` (cada 3 min) |
| `ALERT_COOLDOWN_MINUTES` | Espera antes de volver a mandar la misma alerta | `20` (minutos) |
| `SMTP_USER` | Tu correo Gmail emisor | `tu_correo@gmail.com` |
| `SMTP_PASSWORD` | Tu contraseña de aplicación de 16 letras | `abcd efgh ijkl mnop` |
| `ALERT_EMAIL_TO` | Correo donde quieres recibir las alertas | `mi_correo@gmail.com` |
| `TWILIO_ACCOUNT_SID` | SID de Twilio (si quieres WhatsApp/SMS) | `ACxxxx...` |
| `TWILIO_AUTH_TOKEN` | Token de Twilio | `xxxx...` |
| `TWILIO_WHATSAPP_TO` | Tu WhatsApp con código de país | `whatsapp:+50588888888` |

---

## 💡 Consejos Prácticos para Operar en Nicaragua

1. **Bancos Populares:** En el P2P de Nicaragua, la mayor liquidez y rapidez de liberación se concentra en **BAC Credomatic**, seguido de **Banco LAFISE** y **Banpro (Billetera Móvil)**.
2. **Límites de los Comerciantes:** Si tu presupuesto es de C$1,000, fíjate en el límite mínimo del anuncio; muchos comerciantes piden un mínimo de C$5,000 o más. La app te calcula en la columna *Sugerido* cuánto puedes comprar con tu presupuesto exacto.
3. **Seguridad:** Revisa siempre que el comerciante tenga más del **95% de órdenes completadas** (la app filtra automáticamente a los que tienen menos del 90%).
