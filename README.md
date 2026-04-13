# 🚀 Radar Quant Institucional: TradingLatino + HFT + Order Flow

Un escáner analítico avanzado para criptomonedas (Binance) diseñado para operar como un Fondo de Cobertura (Hedge Fund). Este script no toma decisiones a ciegas basándose solo en el precio; fusiona el **Análisis Técnico Multitemporal**, la **Microestructura del Libro de Órdenes (HFT)** y el **Flujo de Órdenes (Order Flow)** en tiempo real.

El algoritmo actúa como un "escudo", bloqueando entradas falsas y calculando la confluencia matemática exacta para operaciones de Scalping (1H) y Swing (4H).

---

## 🧠 Características Principales

* **📈 Estrategia TradingLatino Pura:** Algoritmos matemáticos nativos (sin depender de TradingView) para calcular el Squeeze Momentum (Regresión Lineal) y el ADX (RMA) en temporalidades de 1D, 4H y 1H.
* **🐋 Order Flow y Manipulación:** Detector de divergencias de CVD (Absorción Alcista y Distribución Bajista) y medidor de la Velocidad de la Cinta (Trades por segundo).
* **🧱 Microestructura HFT:** Lectura profunda del Order Book (5000 niveles) para detectar Muros Institucionales Reales e Imbalance entre Toros y Osos.
* **🧲 Mapa de Calor de Liquidaciones:** Cálculo dinámico del POC (Point of Control) y las "Zonas Imán" donde los minoristas sobre-apalancados (25x, 50x, 100x) serán liquidados.
* **🌍 Filtros Macro y Sentimiento:** Monitoreo en segundo plano de la tendencia del "Rey" (Bitcoin), el Ratio Global Long/Short de los minoristas, el Open Interest y el Funding Rate.
* **🛡️ Gestión de Riesgo (Confluencia):** Sistema de Puntuación de 0% a 100% para validar gatillos, respaldado por un Stop Loss Híbrido Dinámico (Muro de Órdenes + Filtro ATR) y medición del capital (USD) que protege tu Stop Loss.
* **⚡ Inmortalidad de Red:** Construido con `requests.Session`, Exponential Backoff y Threading Locks para soportar micro-cortes de internet y conexiones WebSockets persistentes las 24 horas sin crashear.

---

## 🛠️ Instalación y Requisitos

Este bot requiere **Python 3.9 o superior**.

1. Clona este repositorio o descarga el archivo `.py`:
   ```bash
   git clone [https://github.com/TU_USUARIO/Radar-Quant-HFT.git](https://github.com/TU_USUARIO/Radar-Quant-HFT.git)
