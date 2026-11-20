---
id: pytest_tdd
name: Pytest & Verification Discipline
triggers: test, pytest, prueba, verificar, tdd, unitaria, coverage
---
## Protocolo de Pruebas Automatizadas (Pytest)
1. Nombra los archivos de prueba como 	est_<modulo>.py y las funciones como 	est_<comportamiento_esperado>().
2. Cubre siempre 3 categorías: caso nominal (happy path), casos borde (ceros, vacíos, límites) y casos de error (pytest.raises(...)).
3. Tras crear o modificar código y tests, invoca un_pytest apuntando al archivo de prueba para confirmar que todos pasan antes de cerrar tu etapa.