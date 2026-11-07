# Grid is exclusive of other desk algos on a Market

Superseded 2026-11-07 by [ADR 0025](0025-grid-keeps-its-own-book.md): Grid keeps its own book and runs beside Chase, Ladder and TWAP.

Grid will not start on a Market that already has Chase, Ladder, or TWAP live. Chase, Ladder, and TWAP may still run together on the same Market. Grid already refuses a second Grid on that Market.

Grid’s reduce-only take-profit Clips fight other working children on the same book. Stacking Grid with another desk algo is the combination that actually collides. Refusing only Grid start is enough; a shared “one algo family per Market” lock would block combinations the desk still wants.
