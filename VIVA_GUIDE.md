# VIVA GUIDE — Campus Rescue AI with A* (v3)

## One-minute explanation

"Our university project simulates three emergency types—Medical, Accident and Fire. Cardiac problems come under Medical. We preserved the original campus map and added Store and three specialized exit nodes. After registering an emergency, it automatically finds a responder route and an incident-to-exit route using A*. The large map displays road costs, while the right panel provides a cost reference and live A* calculations for each of the twelve nodes. We also demonstrate route choice explanations, priority scheduling, blocked-road replanning, and completion."

## Viva questions

**1. Why are there three emergency exits?** Medical goes to **Medical Exit**, Accident to **Accident Exit**, and Fire to **Fire Exit**. These are simulated destination nodes connected to the campus roads; their names alone do not make them physically safe exits.

**2. What are the nodes?** Eight original nodes (Gate, Clinic, Library, Hostel, Canteen, Academic, Sports, Lab), plus Store, Medical Exit, Accident Exit and Fire Exit—**12 nodes, 18 edges**.

**3. What is `g(n)`?** The accumulated actual road cost from the chosen start node, in the current search mode. `g(next) = g(current) + road_cost(current,next)`.

**4. What is `h(n)`?** An admissible, straight-line lower-bound estimate from node n to the selected goal. For a fixed goal and optimization mode it **does not change across A* steps**.

**5. What is `f(n)`?** `f(n) = g(n) + h(n)`. A* expands the lowest-f node from OPEN; ties use lower h and then name. The algorithm stores each node's best discovered predecessor.

**6. How can the right panel show g for every node before A* discovers all nodes?** It shows **`g★`**, a separate Dijkstra-computed optimal distance/cost reference for the whole graph. Another column, **`A* g`**, shows the true live value only after A* discovers a node. `f★ = g★ + h`. This avoids pretending unknown A* values were known.

**7. Is Dijkstra replacing A*?** No. Dijkstra only computes the reference table. The route and OPEN/CLOSED exploration use the original A* with live tentative g and the heuristic h; both use identical road restrictions and costs. Tests verify they find the same optimal final cost.

**8. Can we add h(n) to actual g for every road?** No. The next real path cost is previous `g` plus the **edge weight**. The heuristic appears in **f** only; adding it repeatedly to g miscalculates road cost and can break optimality.

**9. How are road costs calculated?** In balanced mode: road distance in km plus estimated travel time in minutes (scoring points). Example: Gate → Clinic, `1.15 km + 2.30 min = 3.45 points`. Traffic and reserved roads affect simulated travel time.

**10. What if an exit route is blocked?** The agent recalculates on the remaining edges; Fire Exit has two approach edges, one from Lab and another from Store. If both are blocked, the UI warns the exit is unreachable.

**11. How do directions appear?** The application reconstructs the path from its predecessors and compares the drawn coordinates of consecutive nodes to describe east/west/north/south/diagonal movements. These are **schematic**, not GPS directions.

**12. What does the Complete checkbox do?** It marks the simulated response complete, frees its reserved roads and assigned vehicle and tries assigning waiting requests by priority.

## Demonstrate

Run `python main.py` → choose **Fire** → verify **Fire Exit** is selected → register **Fire at Hostel** → inspect the right all-node cost panel → click **Trace exit A*** → press **Next step** to explain `g`, `h`, `f`, OPEN, CLOSED, and alternatives → block a road and show replanning → mark incident **Complete**.

**Disclaimer:** Classroom routing demonstration only, not an actual emergency response/evacuation procedure.
