# Algo books own partitioned client_order_index bands

Each algo book allocates Clips from a disjoint client_order_index band: TWAP 7e9–8e9, Chase 8e9–9e9, Ladder 9e9–10e9, Grid 10e9–11e9. Ticket orders allocate below 8e9. Blotter, restore, and kill attribute a venue child from that number alone.

A shared allocator or an extra venue tag would need a round trip we do not have. Changing a band breaks restore of live children and mislabels the blotter. Keep the constants in lockstep on Python and the web plugins.
