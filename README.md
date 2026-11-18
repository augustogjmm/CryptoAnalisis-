# CryptoAnalisis — Monitor técnico y de flujo de órdenes

Proyecto personal de investigación en **Python** que reúne análisis técnico multitemporal, datos de mercado de Binance y observaciones de microestructura. Su propósito es experimentar con integración de APIs, visualización de información y controles para señales simuladas; **no es un sistema de trading institucional validado**.

## Capacidades del prototipo

- Indicadores técnicos en distintas temporalidades, incluyendo EMA, ADX y Squeeze Momentum.
- Consulta y procesamiento de order book, operaciones y métricas públicas disponibles en el proveedor.
- Observaciones de flujo comprador/vendedor, liquidez y contexto de mercado.
- Interfaz de terminal con Rich y registro local para estudio.
- Sesiones HTTP con reintentos y protección ante algunos errores transitorios.

## Ejecución local

Se recomienda Python 3.10 o 3.11 para las versiones de bibliotecas fijadas en el repositorio.

```bash
git clone https://github.com/augustogjmm/CryptoAnalisis-.git
cd CryptoAnalisis-
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python Radar.py
```

## Estructura

- `Radar.py`: script principal de recopilación y análisis.
- `requirements.txt`: bibliotecas Python.
- `leeme.txt`: guía de uso de la versión original.

## Alcance y precauciones

Este repositorio ilustra experimentación con fuentes de datos, análisis e integración. Las métricas no identifican necesariamente intenciones «institucionales» ni permiten anticipar precios con certeza. La disponibilidad depende de servicios externos. No se proporcionan resultados de rentabilidad validados ni recomendaciones de inversión.

No publicar claves ni tokens de Binance o Telegram. Evitar guardar credenciales en el código o en el historial Git.

**Autor:** [Augusto García Juárez Matorras](https://www.linkedin.com/in/augustog/) · [Portfolio ejecutivo](https://github.com/augustogjmm/Radar/blob/main/PORTFOLIO.md)
