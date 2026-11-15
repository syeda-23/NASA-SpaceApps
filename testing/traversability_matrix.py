import numpy as np

grid = np.load(
    "data/processed/traversability_matrix.npy"
)

print("Shape:", grid.shape)
print("Min:", grid.min())
print("Max:", grid.max())
print("Mean:", grid.mean())
print("Std:", grid.std())

print("\nSample values:")

print(
    grid[100:105, 100:105]
)