---
id: security_audit
name: Security & Reliability Audit
triggers: audita, auditoria, seguridad, revisar, vulnerabilidad, owasp, bug
---
## Lista de Verificación de Auditoría Técnica
1. Revisa inyección de comandos (subprocess con shell=True), *path traversal* en manejo de archivos y exposición de secretos o .env.
2. Verifica manejo de excepciones silenciosas (except Exception: pass), fugas de recursos y condiciones de carrera.
3. Publica tu dictamen estructurado en el Blackboard bajo la clave uditoria clasificando hallazgos en [CRÍTICO], [MODERADO] o [OK].