# Runtime Data Directory

This directory contains runtime-generated data that was previously mixed
with configuration files in config/.

## Structure

| Directory | Content |
|---|---|
| data/db/ | SQLite databases (auto_execution, concepts, insights, etc.) |
| data/migration_tracking/ | Phase migration tracking and quality gate artifacts |
| data/*.json | Runtime state files (memory, proactive queue, shadow observations) |

## Note

True configuration files (API keys, user settings, personality matrix, 
feature ownership, route ownership) remain in config/.
