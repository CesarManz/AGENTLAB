---
id: python_clean_code
name: Python Clean Code & Typing
triggers: python, .py, funcion, clase, modulo, refactor, api, fastapi
---
## Estándares de Implementación Python
1. Usa anotaciones de tipo explícitas (Python 3.11+: list[...], dict[...], X | None) en todos los parámetros y valores de retorno.
2. Valida entradas límite (valores nulos, cadenas vacías, división por cero, rutas inválidas) lanzando excepciones estándar claras (ValueError, TypeError, FileNotFoundError).
3. Mantén funciones cohesivas (< 40 líneas) con docstrings concisos que expliquen contrato y excepciones.