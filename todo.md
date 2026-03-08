# TODO - Analisi Miglioramenti fastapi-task-manager

Questo documento analizza i file di esempio (`claudio*.py`) e propone un piano di implementazione per migliorare la libreria.

---

## Panoramica degli Esempi Analizzati

| File | Classe | Concetto Principale |
|------|--------|---------------------|
| `claudio.py` | `MultiStreamPriorityScheduler` | Stream separati per priorità (high/normal) |
| `claudio1.py` / `claudio2.py` | `RobustTaskScheduler` | Sistema robusto con reconciliation e token window |
| `claudio3.py` | `OptimizedReconciliation` | Tracking veloce con Redis SET O(1) |
| `claudio4.py` | `ReconciliationCoordinator` | Coordinator completo con loop di reconciliation |
| `claudio5.py` | `LeaderOnlyConsumerPattern` | Pattern leader/worker con command stream |
| `worker_identity.py` | `WorkerIdentity` | Identificazione univoca dei worker |

---

## 1. Worker Identity (Priorità: ALTA)

**File di riferimento:** `worker_identity.py`

**Stato attuale:** Il runner usa un semplice UUID generato con `uuid4().int`

**Miglioramento proposto:** Implementare una classe `WorkerIdentity` che fornisce:
- Identificazione univoca e tracciabile del worker
- Informazioni diagnostiche (hostname, pid, thread_id)
- Timestamp di avvio
- ID composto leggibile per logging

**Tasks:**
- [ ] Creare `src/fastapi_task_manager/schema/worker_identity.py` (già presente come esempio)
- [ ] Integrare `WorkerIdentity` nel `Runner`
- [ ] Aggiungere worker info nelle statistiche esposte via API
- [ ] Utilizzare `short_id` nei log per debug facilitato

---

## 2. Redis Streams invece di Polling (Priorità: ALTA)

**File di riferimento:** `claudio.py`, `claudio5.py`

**Stato attuale:** Il runner usa polling con `asyncio.sleep(0.1)` per controllare i task da eseguire.

**Miglioramento proposto:** Utilizzare Redis Streams per la coda dei task:
- Pubblicazione task da eseguire in uno stream
- Consumer group per garantire elaborazione unica
- Acknowledgment (ACK) dopo esecuzione

**Vantaggi:**
- Minore carico su Redis (no polling continuo)
- Delivery garantita
- Possibilità di recovery dei task non completati
- Scalabilità orizzontale nativa

**Tasks:**
- [ ] Creare modulo `stream_scheduler.py` per gestione stream
- [ ] Implementare setup automatico consumer group
- [ ] Modificare `Runner` per usare `XREADGROUP` invece di polling
- [ ] Implementare ACK dopo esecuzione task
- [ ] Gestire pending messages per task falliti

---

## 3. Sistema di Priorità Multi-Stream (Priorità: MEDIA)

**File di riferimento:** `claudio.py`

**Stato attuale:** Esiste `high_priority` flag nel task ma la gestione è limitata al semaforo `force_acquire`.

**Miglioramento proposto:** Stream separati per livelli di priorità:
- `tasks:stream:high` - Task critici
- `tasks:stream:normal` - Task standard

**Comportamento:**
- Worker controlla prima stream high, poi normal
- Block timeout diversi per priorità (es. 100ms high, 1s normal)
- Garantisce che task high-priority siano processati prima

**Tasks:**
- [ ] Creare enum `TaskPriority` (HIGH, NORMAL, LOW)
- [ ] Implementare routing automatico ai diversi stream
- [ ] Modificare worker loop per controllare stream in ordine di priorità
- [ ] Aggiungere metriche per latenza per priorità

---

## 4. Reconciliation System (Priorità: ALTA)

**File di riferimento:** `claudio3.py`, `claudio4.py`

**Stato attuale:** Se un task viene perso (es. crash durante scheduling), non c'è meccanismo di recovery.

**Miglioramento proposto:** Sistema di reconciliation periodico:

### 4.1 Tracking Set (approccio ottimizzato da `claudio3.py`)
- Mantiene `tasks:scheduled` SET per tracking O(1)
- Mantiene `tasks:running:{task_name}` key per task in esecuzione
- Verifica rapida senza scansione stream

### 4.2 Reconciliation Loop (da `claudio4.py`)
- Ogni N secondi verifica task "overdue"
- Se task è overdue e non in stream/running -> ri-pubblica
- Log dettagliato per debug

**Tasks:**
- [ ] Creare modulo `reconciliation.py`
- [ ] Implementare tracking set per task schedulati
- [ ] Implementare tracking per task in esecuzione
- [ ] Creare reconciliation loop nel coordinator
- [ ] Aggiungere configurazione `reconciliation_interval` in `Config`
- [ ] Aggiungere metriche per task riconciliati

---

## 5. Leader Election e Coordinator Pattern (Priorità: MEDIA)

**File di riferimento:** `claudio5.py`

**Stato attuale:** Ogni istanza ha il proprio runner che compete per il lock del task.

**Miglioramento proposto (opzionale):** Pattern Leader/Follower:
- Un solo "coordinator" (leader) schedula i task
- Tutti i worker eseguono i task dallo stream
- Leader election via Redis lock

**Vantaggi:**
- Scheduling centralizzato più predicibile
- Riduzione race conditions
- Semplifica reconciliation

**Svantaggi:**
- Singolo punto di failure (mitigato da failover)
- Maggiore complessità

**Tasks:**
- [ ] Valutare se implementare (discussione architetturale)
- [ ] Se sì: implementare leader election con Redis lock + TTL
- [ ] Se sì: separare logica coordinator da worker
- [ ] Se sì: implementare command stream per operazioni admin

---

## 6. Miglioramenti Redis Keys (Priorità: BASSA)

**Stato attuale:** Le chiavi Redis sono costruite con concatenazione di stringhe nel codice.

**Miglioramento proposto:**
- Creare classe `RedisKeyBuilder` per costruzione chiavi
- Centralizzare pattern delle chiavi
- Documentare tutti i key patterns

**Tasks:**
- [ ] Creare `redis_keys.py` con costanti e builder
- [ ] Refactor runner.py per usare il builder
- [ ] Aggiornare documentazione con key patterns

---

## 7. Miglioramento Storage Statistiche (Priorità: BASSA)

**Stato attuale:** Runs e durations salvate come stringhe separate da `\n` in Redis.

**Miglioramento proposto:** Usare Redis List (`LPUSH`/`LTRIM`) invece di stringhe:
- Operazioni atomiche
- `LTRIM` per limitare automaticamente la lista
- Niente parsing manuale

**Tasks:**
- [ ] Migrare `_runs` a Redis List
- [ ] Migrare `_durations_second` a Redis List
- [ ] Aggiungere migration script per dati esistenti

---

## 8. Gestione Errori e Retry (Priorità: MEDIA)

**Stato attuale:** Se un task fallisce, l'errore viene loggato ma non c'è retry.

**Miglioramento proposto:**
- Configurazione retry per task (max_retries, backoff)
- Dead Letter Queue per task falliti definitivamente
- Metriche errori per task

**Tasks:**
- [ ] Aggiungere `max_retries` e `retry_backoff` a Task schema
- [ ] Implementare retry logic nel worker
- [ ] Creare DLQ stream per task falliti
- [ ] Aggiungere endpoint API per visualizzare/riprovare task falliti

---

## Piano di Implementazione Suggerito

### Fase 1 - Fondamenta (Breaking changes minimi)
1. Worker Identity
2. Redis Key Builder
3. Storage statistiche con Lists

### Fase 2 - Core Improvements
4. Redis Streams base
5. Reconciliation System
6. Gestione Errori e Retry

### Fase 3 - Advanced Features
7. Sistema Priorità Multi-Stream
8. Leader Election (opzionale)

---

## Note Tecniche

### Compatibilità
- Valutare migration path per utenti esistenti
- Considerare feature flags per nuove funzionalità
- Mantenere backward compatibility dove possibile

### Testing
- Ogni feature richiede unit test
- Aggiungere integration test con Redis reale
- Test di failover e recovery

### Documentazione
- Aggiornare README con nuove features
- Documentare architettura Redis Streams
- Aggiungere esempi per nuovi pattern

---

## NUOVA SEZIONE: Findings Analisi Multi-Agente

### Bug Critici da Fixare IMMEDIATAMENTE

#### 1. Race Condition nel Lock Distribuito (`runner.py:131-153`)

**Problema**: Pattern `EXISTS` + `SET` non atomico

```python
# ATTUALE (VULNERABILE)
redis_uuid_exists = await self._redis_client.exists(...)
if not redis_uuid_exists:
    await self._redis_client.set(..., ex=15)
    await asyncio.sleep(0.2)  # Workaround fragile!
```

**Fix**: Usare `SET NX` (atomico)
```python
lock_acquired = await self._redis_client.set(
    lock_key, self._uuid, nx=True, ex=15
)
if not lock_acquired:
    return
```

#### 2. Pattern Anti-Pattern EXISTS + GET (`runner.py:79-96`)

**Problema**: Due round-trip Redis invece di uno

```python
# ATTUALE (INEFFICIENTE)
if await self._redis_client.exists(key):
    value = await self._redis_client.get(key)

# FIX
value = await self._redis_client.get(key)
if value is not None:
    ...
```

**Impatto**: -50% operazioni Redis immediate

---

### Proiezioni Performance (100 tasks, 10 workers)

| Metrica | Polling Attuale | Quick Fixes | Redis Streams |
|---------|-----------------|-------------|---------------|
| Redis ops/sec (idle) | 20,000 | 10,000 | 100-200 |
| Latenza pickup task | 53ms avg | 53ms | 3ms |
| CPU worker (idle) | 15-20% | 10-12% | 1-2% |
| Redis CPU | 10-15% | 5-8% | 1-2% |
| Memory Redis | 300KB | 300KB | 3MB |

---

### Architettura Raccomandata: Redis Streams Hybrid

```
+------------------+     +-----------------+     +------------------+
|  Cron Scheduler  | --> |  Redis Stream   | --> |  Worker Consumers|
|  (evaluates cron)|     |  (Task Queue)   |     |  (XREADGROUP)    |
+------------------+     +-----------------+     +------------------+
        |                        |                        |
        v                        v                        v
   ZSET pending            Stream entries           Task execution
   (score=next_run)        (ready tasks)            (with XACK)
```

---

### Lua Scripts Richiesti per Atomicità

Le operazioni multi-step in `claudio3.py` e `claudio4.py` richiedono Lua scripts:

```lua
-- publish_task.lua (esempio)
local stream = KEYS[1]
local scheduled_set = KEYS[2]
local pending_zset = KEYS[3]
local task_name = ARGV[1]

local msg_id = redis.call('XADD', stream, '*', 'task_name', task_name, ...)
redis.call('SADD', scheduled_set, task_name)
redis.call('ZREM', pending_zset, task_name)
return msg_id
```

---

### Roadmap Aggiornata (5 Fasi)

#### Fase 0 - Quick Wins (1-2 giorni) ⚡ NUOVA
- [ ] Fix race condition lock con `SET NX`
- [ ] Rimuovere pattern `EXISTS` + `GET`
- [ ] Pipeline operazioni statistiche
- [ ] Ridurre frequenza lock renewal (da 10/sec a 0.5/sec)

#### Fase 1 - Fondamenta (1-2 settimane)
- [ ] Worker Identity
- [ ] Redis Key Builder
- [ ] Storage statistiche con Lists
- [ ] Configurazione: `worker_service_name`, `poll_interval`, `lock_ttl`

#### Fase 2 - Redis Streams Core (2-3 settimane)
- [ ] `StreamScheduler` class
- [ ] `StreamConsumer` class con XREADGROUP
- [ ] Consumer group initialization
- [ ] ACK logic
- [ ] Feature flag: `use_streams: bool = False`
- [ ] Config: `stream_max_len`, `stream_block_ms`

#### Fase 3 - Reconciliation & Recovery (1-2 settimane)
- [ ] `ReconciliationService` class
- [ ] Tracking SET per task schedulati
- [ ] Running task tracking con TTL keys
- [ ] Pending message recovery on startup
- [ ] Config: `reconciliation_interval_seconds`, `task_running_ttl_seconds`

#### Fase 4 - Priority Streams (1 settimana)
- [ ] `TaskPriority` enum
- [ ] Multi-stream routing
- [ ] Priority-ordered consumption

#### Fase 5 - Error Handling & DLQ (1-2 settimane)
- [ ] `max_retries`, `retry_backoff` in Task schema
- [ ] Exponential backoff retry logic
- [ ] Dead Letter Queue stream
- [ ] API endpoints per DLQ management

---

### Rischi e Mitigazioni

| Rischio | Impatto | Probabilità | Mitigazione |
|---------|---------|-------------|-------------|
| Learning curve Redis Streams | Medio | Alta | Documentazione, test, feature flag off by default |
| Migration path utenti esistenti | Alto | Media | Version detection, auto-migration, upgrade docs |
| Memory usage streams | Medio | Media | `MAXLEN ~`, configurable retention |
| Consumer group race on startup | Medio | Bassa | `XGROUP CREATE ... MKSTREAM` con error handling |

---

### Nuove Configurazioni da Aggiungere a `Config`

```python
class Config(BaseModel):
    # ... existing ...

    # Fase 0 - Quick wins
    poll_interval: float = 0.1
    lock_renewal_interval: float = 2.0
    running_lock_ttl: int = 5

    # Fase 1 - Foundation
    worker_service_name: str = "fastapi-task-manager"

    # Fase 2 - Streams
    use_streams: bool = False
    stream_max_len: int = 10000
    stream_block_ms: int = 1000

    # Fase 3 - Reconciliation
    reconciliation_enabled: bool = True
    reconciliation_interval_seconds: int = 30
    task_running_ttl_seconds: int = 3600
```

---

## File da Rimuovere dopo Implementazione

I seguenti file sono esempi/prototipi e vanno rimossi dopo aver completato l'implementazione:
- `claudio.py`
- `claudio1.py`
- `claudio2.py`
- `claudio3.py`
- `claudio4.py`
- `claudio5.py`
- `src/fastapi_task_manager/schema/worker_identity.py` (da integrare nel progetto, non rimuovere)
