# ZotMD

**Sync your Zotero library to Markdown files with automatic updates and PDF annotation extraction.**

Perfect for use with Obsidian, Logseq, or any Markdown-based note-taking app.

## Features

- 📚 **Smart Sync**: Incremental sync only updates changed items
- 📝 **PDF Annotations**: Automatically extracts highlights and notes
- 🎨 **Customizable Templates**: Use Jinja2 templates to format your notes
- 🔑 **Citation Keys**: Uses Better BibTeX for consistent filenames
- 💾 **User Notes**: Preserves your custom notes across syncs
- ⚙️ **Configurable**: Simple TOML configuration

## Quick Start

```bash
# Install with uv (https://docs.astral.sh/uv/)
uv tool install zotmd

# Set up configuration
zotmd init

# Sync your library
zotmd sync
```

## Requirements

- Python 3.13+
- [Better BibTeX](https://retorque.re/zotero-better-bibtex/) (Zotero plugin)
- Zotero API access

## Documentation

📖 **[Full Documentation](https://adbX.github.io/zotmd/)**

- [Installation Guide](https://adbX.github.io/zotmd/installation/)
- [Getting Started](https://adbX.github.io/zotmd/getting-started/)
- [Usage & Commands](https://adbX.github.io/zotmd/usage/)
- [Configuration](https://adbX.github.io/zotmd/configuration/)
- [Troubleshooting](https://adbX.github.io/zotmd/troubleshooting/)

## Example Output

```markdown
---
title: "Reproscreener: Leveraging LLMs for Assessing Computational Reproducibility of Machine Learning Pipelines"
citekey: "bhaskarReproscreenerLeveragingLLMs2024"
itemType: conferencePaper
venue: "Association for Computing Machinery"
year: 2024
dateAdded: 2025-02-08
authors:
  - "Adhithya Bhaskar"
  - "Victoria Stodden"
status: unread
tags:
  - automated-checks
  - metrics
  - tools/LLM
  - references
links:
  - "zotero://select/library/items/RUNIG8WJ"
  - "https://doi.org/10.1145/3641525.3663629"
  - "https://doi.org/10.1145/3641525.3663629"
aliases:
  - "Reproscreener Leveraging LLMs for Assessing Computational Reproducibility of Machine Learning Pipelines"
  - "bhaskarReproscreenerLeveragingLLMs2024"
---

# @bhaskarReproscreenerLeveragingLLMs2024


> [!abstract]-
> The increasing reliance on machine learning models in scientific research and day-to-day applications – and the near-opacity of their associated computational methods – creates a widely recognized need to enable others to verify results coming from Machine Learning Pipelines. In this work we use an empirical approach to build on efforts to define and deploy structured publication standards that allow machine learning research to be automatically assessed and verified, enabling greater reliability and trust in results. To automate the assessment of a set of publication standards for Machine Learning Pipelines we developed Reproscreener; a novel, open-source software tool (see https://reproscreener.org/). We benchmark Reproscreener’s automatic reproducibility assessment against a novel manually labeled “gold standard” dataset of machine learning arXiv preprints. Our empirical evaluation has a dual goal: to assess Reproscreener’s performance; and to uncover gaps and opportunities in current reproducibility standards. We develop reproducibility assessment metrics we called the Repo Metrics to provide a novel overall assessment of the re-executability potential of the Machine Learning Pipeline, called the ReproScore. We used two approaches to the automatic identification of reproducibility metrics, keywords and LLM tools, and found the reproducibility metric evaluation performance of Large Language Model (LLM) tools superior to keyword associations.


# Notes

%% begin notes %%
-----------------------
%% end notes %%

# Annotations

%% begin annotations %%
- <mark class="hltr-purple">We adapt the following three criteria from prior work [15]: (1) README file presence:</mark> [Page 103](zotero://open-pdf/library/items/PN6G5V8A?page=2&annotation=6PZJVP8Y)
- <mark class="hltr-purple">(2) Wrapper scripts:</mark> [Page 103](zotero://open-pdf/library/items/PN6G5V8A?page=2&annotation=D4FD7GNU)
- <mark class="hltr-purple">(3) Software dependencies:</mark> [Page 103](zotero://open-pdf/library/items/PN6G5V8A?page=2&annotation=E6V5IGGC)
- <mark class="hltr-green">Reproscreener’s architecture has 3 key stages: Ingest, Evaluate and Report. First, it analyzes the preprint’s TEX files and repository contents, including README files and filenames. Next, keyword searches based on predefined criteria are performed on the parsed data which return a set of pass and fail results used to generate a reproducibility score. Along with these scores, Reproscreener5 provides a table highlighting areas for improvement.</mark> [Page 103](zotero://open-pdf/library/items/PN6G5V8A?page=2&annotation=ZFFVD2VA)
- <mark class="hltr-green">There are three evaluations:  (1) The 9 selected Gunderson metrics on the full text of the preprint. (2) The 9 selected Gunderson metrics on the abstract. (3) The 6 Repo Metrics on the code repositories.</mark> [Page 105](zotero://open-pdf/library/items/PN6G5V8A?page=4&annotation=4QS5BUN5)
- <mark class="hltr-red">We find that researchers often include the experimental setup (74%) and dataset (62%) but details such as the problem, objective, hypothesis, and research questions were mentioned less frequently. ReproScreener performed best on the ‘Code Available’ metric (82%) which is not surprising since this metric is assessed by extracting and parsing URLs from the preprint as opposed to keyword searches for other metrics, where the latter is more likely to have false positives.</mark> [Page 107](zotero://open-pdf/library/items/PN6G5V8A?page=6&annotation=5QGJXVA5)
%% end annotations %%

## Related Literature

## Annotation Color Key

## Formatted bibliography
[1]

Adhithya Bhaskar, Victoria Stodden, "Reproscreener: Leveraging LLMs for Assessing Computational Reproducibility of Machine Learning Pipelines," _Unknown_, pp. 101–109, July 11, 2024, doi: [10.1145/3641525.3663629](https://doi.org/10.1145/3641525.3663629).


%% Import Date: 2025-12-26T19:27:41.672+03:00 %%
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please see the [documentation](https://adbX.github.io/zotmd/) for development setup.

## Support

- 📝 [Report Issues](https://github.com/adbX/zotmd/issues)
- 💬 [Discussions](https://github.com/adbX/zotmd/discussions)
- 📖 [Documentation](https://adbX.github.io/zotmd/)
