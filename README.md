# qb-tracker-sentinel

Per-tracker seeding limits per qBittorrent via Web API: lo script monitora i torrent in seeding e li ferma automaticamente quando superano soglie di **ratio**, **tempo di seeding attivo** o **idle** (assenza di upload) diverse per ogni tracker.

## Perché
qBittorrent permette limiti globali/categoria, ma non per-tracker. qb-tracker-sentinel colma il gap applicando regole granulari per host di tracker (es. `tracker.example.org`).

## Caratteristiche
- Regole per-tracker con soglie di:
  - ratio (upload/download)
  - minuti di seeding (solo da quando il torrent è in seed)
  - minuti di inattività (nessun upload per X minuti)
- Azioni configurabili: `pause` (default) o `remove` (opzionale, con o senza dati).
- Dry-run per testare senza toccare i torrent.
- Log puliti con motivi dello stop (ratio, seeding_time, idle).
- Supporto tag/categorie opzionali per includere/escludere torrent.
- Funziona su seedbox: nessun bisogno di Docker o privilegi root.

## Requisiti
- Python 3.9+
- qBittorrent con WebUI abilitata
- Pacchetti Python: `qbittorrent-api`, `PyYAML`

## Installazione
```bash
git clone https://github.com/davidesidoti/qb-tracker-sentinel.git
cd qb-tracker-sentinel
python -m venv .venv
source .venv/bin/activate  # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Crea `config.yaml` nella root del progetto.

## Configurazione (`config.yaml`)
```yaml
qbittorrent:
  host: "http://127.0.0.1:8080"
  username: "admin"
  password: "password"
  verify_ssl: false
  timeout: 15

policy:
  default:
    ratio: 2.0             # stop se ratio >= 2.0
    seeding_minutes: 720   # stop dopo 12 ore di seeding
    idle_minutes: 60       # stop se nessun upload per 60 min
    action: pause          # pause | remove | remove_data
    include_tags: []       # opzionale: limita ai torrent con questi tag
    exclude_tags: []       # opzionale: escludi questi tag

  trackers:
    "tracker.example.org":
      ratio: 1.0
      seeding_minutes: 180
      idle_minutes: 15
      action: pause

    "anothertracker.tld":
      ratio: 3.0
      action: remove

runtime:
  interval_seconds: 60     # frequenza di polling
  dry_run: true            # true = non applica azioni
  log_level: "INFO"
```

Note utili:
- `seeding_minutes` usa il campo `seeding_time` di qBittorrent.
- `idle_minutes` viene valutato osservando `uploaded` e/o `upspeed`: se non cresce e la velocità è zero per X minuti, lo script considera il torrent idle.
- Se una regola per-tracker non specifica un campo, eredita il valore da `default`.

## Esecuzione
```bash
python sentinel.py --config config.yaml
```

Parametri utili:
- `--once` esegue un solo ciclo di controllo ed esce.
- `--dry-run` forza il dry-run a prescindere dal file di config.

## Avvio in background (seedbox friendly)
### Cron (semplice)
```bash
*/5 * * * * /path/qb-tracker-sentinel/.venv/bin/python /path/qb-tracker-sentinel/sentinel.py --config /path/qb-tracker-sentinel/config.yaml >> /path/qb-tracker-sentinel/sentinel.log 2>&1
```

### Supervisord (se disponibile sul provider)
`/etc/supervisor/conf.d/qb-tracker-sentinel.conf`:
```ini
[program:qb-tracker-sentinel]
command=/path/qb-tracker-sentinel/.venv/bin/python /path/qb-tracker-sentinel/sentinel.py --config /path/qb-tracker-sentinel/config.yaml
directory=/path/qb-tracker-sentinel
autostart=true
autorestart=true
stderr_logfile=/path/qb-tracker-sentinel/err.log
stdout_logfile=/path/qb-tracker-sentinel/out.log
```

## Strategia di matching per tracker
Lo script legge i tracker del torrent e normalizza l'host (es. `https://tracker.example.org/announce` → `tracker.example.org`). La prima regola che combacia vince; se nessuna combacia, usa `default`.

## Cosa fa quando scatta una soglia
- `pause`: mette in pausa il torrent
- `remove`: rimuove il torrent (mantiene i dati)
- `remove_data`: rimuove torrent e dati (usa con cautela)

Ogni stop viene loggato con: `AZIONE | hash | nome | tracker | motivo`.

## Best practice
- Testa sempre con `dry_run: true` e `--once` prima di automatizzare.
- Per i tracker privati, rispetta le policy: molti richiedono ratio/tempo minimi. Imposta soglie più conservative dei loro minimi.
- Valuta tag/categorie per non toccare torrent “pinned” o a bassa disponibilità.

## Dipendenze
`requirements.txt`:
```
qbittorrent-api>=2025.7.0
PyYAML>=6.0.1
```

## Esempio di struttura progetto
```
qb-tracker-sentinel/
├─ sentinel.py
├─ config.yaml
├─ README.md
└─ requirements.txt
```

## Licenza
MIT
```

