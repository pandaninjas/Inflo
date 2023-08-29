import argparse
from main import MusicPlayer

parser = argparse.ArgumentParser(
    prog="Inflo Weights Generator",
    description="A program to show generated percentages from Inflo weights",
)

parser.add_argument("--weights", required=False)
args = parser.parse_args()

player = MusicPlayer(None, None, args.weights, True)
keys, weights = player.generate_weights()
total = sum(weights)
combined = []
for item in range(len(keys)):
    combined.append((keys[item], round(weights[item] * 100 / total, 2)))

for item in sorted(combined, key=lambda k: k[1]):
    print(f"{item[0]}: {item[1]}%")