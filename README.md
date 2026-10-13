# Aegis
# AEGIS – AI-Based Multi-Agent Emergency Response Simulation

AEGIS is an AI-based emergency response simulation that models a virtual city as a weighted graph and uses classical Artificial Intelligence techniques to determine efficient routes and decisions for emergency vehicles.

The system simulates emergency vehicles such as ambulances, police vehicles, fire trucks, and rescue vehicles responding to incidents across a dynamically changing city environment.

## Features

- Weighted city graph with locations and road distances
- BFS, DFS, Uniform Cost Search (UCS), and A* search
- Path distance and estimated response-time calculation
- Emergency vehicle and incident simulation
- Heuristic-based decision making
- Dynamic road closures and rerouting
- Constraint-based emergency resource allocation
- Intelligent agents for emergency vehicles
- Planning and knowledge-based reasoning
- Pygame-based interactive visualization
- Simulation performance comparison and analytics
- Natural-language scenario/prompt engine (planned)

## AI Techniques

The project integrates multiple AI concepts:

- **BFS & DFS** – Uninformed search
- **UCS** – Cost-based search
- **A\*** – Heuristic search
- **Heuristics** – Incident prioritization
- **CSP & Backtracking** – Resource allocation
- **Planning** – Future-state decision making
- **Knowledge Representation** – Emergency rules and facts
- **Intelligent Agents** – Autonomous emergency vehicles

## Project Structure

Aegis/
├── ai/                # AI decision-making components
├── algorithms/        # BFS, DFS, UCS and A* implementations
├── data/              # City and simulation data
├── environment/       # City and road environment
├── prompt_engine/     # Scenario processing
├── results/           # Simulation results
├── simulation/        # Simulation engine
├── visualization/     # Pygame visualization
├── main.py            # Main entry point
└── requirements.txt   # Dependencies

## Technology Stack

- Python
- Pygame CE
- NetworkX
- Matplotlib
- JSON
- Git & GitHub
Running the Project
Clone the repository:
git clone https://github.com/vkamboj07/Aegis.git
cd Aegis

## Install dependencies:
pip install -r requirements.txt

## Run the simulation:
python main.py

## Team
- Aryan Bhutani – 240406
- Vaibhav Kamboj – 240678
- Samaira – 240628
  
## Project Goal
The goal of AEGIS is to demonstrate how classical AI techniques can be combined to create an adaptive, multi-agent emergency response system capable of making decisions and responding to changing environmental conditions.

