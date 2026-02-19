# Ejecucion: quien lo corre y como (incluyendo SSH)

## Quien debe ejecutarlo?
- Normalmente tu / tu equipo en tu maquina o servidor.
- Yo (agente) puedo preparar archivos, scripts y comandos dentro de este entorno de trabajo, pero no puedo abrir una sesion SSH interactiva a tus servidores privados por mi cuenta.

## Opciones reales de ejecucion

### Opcion A - Local (rapida)
```bash
cd /workspace/Biblioteca
bash openclaw-enterprise/scripts/run_enterprise_stack.sh
```

### Opcion B - En servidor por SSH (recomendada para operacion continua)
Desde tu terminal local:

```bash
ssh usuario@tu-servidor
cd /ruta/del/repo/Biblioteca
bash openclaw-enterprise/scripts/run_enterprise_stack.sh
```

### Opcion C - Servicio gestionado
- Docker + systemd/PM2 para dejarlo corriendo.
- Cron para heartbeat y jobs periodicos.

## Como decirle a OpenClaw que ejecute?
Con una invocacion del runtime apuntando al config del control-plane:

```bash
openclaw run --config openclaw-enterprise/control-plane/openclaw.json --task "Procesar estados financieros Q1"
```

Si tu version de OpenClaw usa otra sintaxis CLI, conserva la misma idea:
- cargar `openclaw.json`,
- definir tarea,
- respetar HITL (`/approve`) antes de acciones irreversibles.

## Seguridad minima antes de ejecutar en servidor
- Usar usuario no-root para el proceso.
- Guardar credenciales via variables de entorno/secret manager.
- Restringir acceso de red al puerto de base de datos.
- Respaldos de `mem_finance`, `mem_tech`, `mem_audit`.