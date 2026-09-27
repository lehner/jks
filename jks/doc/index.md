# jks scripts

Reference pages of the command-line tools; `jks_gui` shows them with the `?` buttons.

## Building tags

| script | |
|---|---|
| [`jks_add`](jks_add.md) | Adds new tags computed from Python expressions over the existing tags of a database. |
| [`jks_add_parameter`](jks_add_parameter.md) | Adds fixed external parameters with an optional error to an existing database. |
| [`jks_add_sys`](jks_add_sys.md) | Attaches systematic variations to a tag, taking each shifted value from another tag. |
| [`jks_rescale_variance`](jks_rescale_variance.md) | Multiplies the variance of tags by given factors, in place. |
| [`jks_set_variance`](jks_set_variance.md) | Rescales single elements of tags so that their total error is a given fraction of the value. |
| [`jks_correlator_reconstruct`](jks_correlator_reconstruct.md) | Builds correlators `sum_{i<N} c2[i] exp(-t E[i])` from tags of energies and amplitudes, one output tag per number of states N. |
| [`jks_values`](jks_values.md) | Prints the elements of a constant tag, one per line, for use in shell loops. |

## Spectral reconstruction

| script | |
|---|---|
| [`jks_plsa`](jks_plsa.md) | Stores the exact spectral-positivity band of output weights, given data at input weights, as a new tag. |
| [`jks_blsa`](jks_blsa.md) | Stores the exact band of output weights under a box prior lower <= z <= upper on the spectral weights, as a new tag. |
| [`jks_hlt`](jks_hlt.md) | Stores the linear Hansen-Lupo-Tantalo (HLT) estimate g.C of output weights, with its jackknife blocks, as a new tag. |
| [`jks_hlt_kernel`](jks_hlt_kernel.md) | Stores the HLT reconstructed kernels kbar that `jks_hlt` would use, one grid-array tag per output weight. |

## Fits and GEVP

| script | |
|---|---|
| [`jks_model_average`](jks_model_average.md) | Weighted average of one parameter over several fit results, with the spread of the models stored as a systematic variation. |
| [`jks_fit`](jks_fit.md) | Uncorrelated least-squares fit of one or more tags to user-supplied functions; jackknife blocks are obtained by Hessian linearization around the central fit. |
| [`jks_slow_fit`](jks_slow_fit.md) | Same fit as `jks_fit`, but every jackknife block (and variation) is refitted by a full minimization instead of the Hessian linearization. |
| [`jks_gevp_2pt`](jks_gevp_2pt.md) | Solves the generalized eigenvalue problem of a matrix of two-point correlators time slice by time slice and writes energies, overlaps and eigenvectors to a new database. |
| [`jks_gevp_2pt_tref`](jks_gevp_2pt_tref.md) | Like `jks_gevp_2pt`, but the correlator matrix is first rotated with the GEVP eigenvectors of a fixed reference time `tref` before the per-time-slice GEVP is solved. |
| [`jks_gevp_2pt_basis_change`](jks_gevp_2pt_basis_change.md) | Rotates a correlator matrix into the basis of GEVP eigenvectors taken at a fixed time slice, `C_nm(t) = u_n^† C(t) u_m`, optionally also with one side left in the original operator basis. |

## Importing data

| script | |
|---|---|
| [`jks_add_from`](jks_add_from.md) | Copies tags from another database into a database, optionally renaming them. |
| [`jks_merge`](jks_merge.md) | Merges all tags of several databases into a new database. |
| [`jks_tagged_merge`](jks_tagged_merge.md) | Merges several databases into a new one, prefixing each input's tags with a given label. |
| [`jks_create_parameter`](jks_create_parameter.md) | Creates a new database holding fixed parameters with optional errors. |
| [`jks_create_correlator_from_corrfile`](jks_create_correlator_from_corrfile.md) | Creates a new jks database from binary corrIO files, one file per configuration, with the real and imaginary part of every correlator as separate tags. |
| [`jks_create_correlator_from_corrfile_novar`](jks_create_correlator_from_corrfile_novar.md) | Variant of `jks_create_correlator_from_corrfile` that numbers the configurations by their position in the file list instead of taking the number from the file name. |
| [`jks_create_correlator_from_textfile`](jks_create_correlator_from_textfile.md) | Creates a new jks database with one tag from text files, one file per configuration, of the form `t value`. |
| [`jks_create_correlator_from_multi_textfile`](jks_create_correlator_from_multi_textfile.md) | Creates a new jks database with one tag from text files of several ensembles or streams, each given by its own prefix and file pattern. |
| [`jks_tagged_merge_auto`](jks_tagged_merge_auto.md) | Merges several databases into a new one, prefixing each input's tags with its file name. |

## Selecting and pruning

| script | |
|---|---|
| [`jks_rm`](jks_rm.md) | Removes tags matching shell-style patterns from a database, in place. |
| [`jks_compress`](jks_compress.md) | Drops configurations and variations on which no tag depends. |
| [`jks_take`](jks_take.md) | Writes the tags of a database that match given patterns into a new database. |

## Inspecting

| script | |
|---|---|
| [`jks_info`](jks_info.md) | Prints a database overview, or the values of a tag with statistical and systematic errors. |
| [`jks_cor`](jks_cor.md) | Prints the statistical, systematic and total correlation between two elements of a database. |
| [`jks_extract_config`](jks_extract_config.md) | Prints the single-configuration measurement of a tag, reconstructed from its delete-one jackknife block. |
| [`list-corrs`](list-corrs.md) | Lists the record headers (tag, size, flags, checksum) of a binary correlator file. |
| [`dump-corrs`](dump-corrs.md) | Prints the contents of a binary correlator file as text, optionally only one tag. |

## Plotting

| script | |
|---|---|
| [`jks_plot2`](jks_plot2.md) | Drop-in replacement for `jks_plot` that draws the same plots with matplotlib, without gnuplot, pdfcrop or exiftool. |
| [`jks_plot`](jks_plot.md) | Plots tags of a jks database with gnuplot into a (multi-page) PDF, driven by a list of short plot commands. |
| [`jks_plot_dist`](jks_plot_dist.md) | Diagnostic plots (histogram, binning, sub-sample and autocorrelation checks) of the per-configuration distribution of one element of a tag. |

## Flows and GUI

| script | |
|---|---|
| [`jks_flow`](jks_flow.md) | Run, inspect and edit a data flow: a bash file of `jks_*` steps whose results are cached. |
| [`jks_gui`](jks_gui.md) | Graphical browser for jks databases and designer of data flows, served as a local web page. |

## Deprecated

`jks_dup` and `jks_dump_blocks` are python 2 scripts and will be removed.
