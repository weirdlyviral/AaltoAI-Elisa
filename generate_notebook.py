import json

with open("visualize.ipynb", "r") as f:
    notebook = json.load(f)

for cell in notebook["cells"]:
    if cell["cell_type"] == "code" and "sns.histplot" in "".join(cell["source"]):
        cell["source"] = [
            "plt.figure(figsize=(10, 5))\n",
            "# Filter out 0s to see the actual distribution of video watchers\n",
            "video_users = df_anon[df_anon['im_video_GB_sum'] > 0]\n",
            "sns.histplot(data=video_users, x='im_video_GB_sum', bins=50, kde=True, color='purple')\n",
            "plt.title('Distribution of Video Data Usage (Non-Zero, Top-Coded at p99)')\n",
            "plt.xlabel('Video Usage (GB)')\n",
            "plt.ylabel('Number of Sessions')\n",
            "plt.show()"
        ]

with open("visualize.ipynb", "w") as f:
    json.dump(notebook, f, indent=1)
