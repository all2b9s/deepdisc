import glob
import json
import ntpath
import os
from pathlib import Path

import numpy as np
import random
import shutil
from iopath.common.file_io import file_lock
from detectron2.utils.file_io import PathManager
import logging
logger = logging.getLogger(__name__)



class DDLoader:
    """A base deepdisc data loader class"""

    def __init__(self):
        self.filedict = None
        self.dataset = None

    def get_dataset(self):
        """retrieves the list of dataset_dicts if established."""
        return self.dataset

    def generate_filedict(
        self, dirpath, filters, img_files, mask_files, subdirs=False, filt_loc=0, n_samples=None
    ):
        """Generates a path dictionary from a directory of files.

        Parameters
        ----------
        dirpath : str, path-like
            The path to the data directory.
        filters : list
            A list of filters available in the dataset. The filter names should
            match some string identifier in the name itself. E.g. img_r.fits
            will be matched to a filter with label "r"
        img_files: str
            The name of the image files to collect, should have a "*" to
            collect all image files in the dataset. E.g. 001_img.fits can be
            caught used img_files = "*_img.fits"
        maskfiles: str
            The name of the mask files to collect, should have a "*" to
            collect all mask files in the dataset. E.g. 001_mask.fits can be
            caught used mask_files = "*_mask.fits"
        subdirs: bool
            Indicates whether the data is stored within subdirectories within
            the dirpath. If True, will recursively search for files.
        filt_loc: int
            The integer location of the filter within the image name, used to
            split files across filters accordingly. E.g. 001_img_r.fits would
            have a filt_loc of 8 (or -6).
        n_samples: int
            If specified, filters down to a subset of the dataset that contains
            `n_samples` image files per filter.

        Returns
        -------
        self : DataLoader
            A `DataLoader` with a filename dictionary generated in
            `DataLoader.filedict`
        """

        # Setup filenames dict
        filenames_dict = {}
        filenames_dict["filters"] = filters

        # Glob in filenames from the paths
        if subdirs:
            imgs = sorted(glob.glob(os.path.join(dirpath, "*","*","*", img_files)))
            masks = sorted(glob.glob(os.path.join(dirpath, "*","*","*", mask_files)))
        else:
            imgs = sorted(glob.glob(os.path.join(dirpath, img_files)))
            masks = sorted(glob.glob(os.path.join(dirpath, mask_files)))

        # Assign files to the dictionary by filter
        # Requires good assignment of the img_files and filt_loc parameters
        for filt in filenames_dict["filters"]:
            filenames_dict[filt] = {}
            if n_samples:
                filenames_dict[filt]["img"] = [f for f in imgs if ntpath.basename(f)[(filt_loc-len(filt)+1):(filt_loc+1)] == filt][
                    0:n_samples
                ]
            else:
                filenames_dict[filt]["img"] = [f for f in imgs if ntpath.basename(f)[filt_loc] == filt]
        # confirm (or raise exception) that all filters have the same number of files
        self._verify_input_file_count(filenames_dict)
        print(len(masks))
        if n_samples:
            masks = masks[0:n_samples]
        filenames_dict["mask"] = masks
        filenames_dict["index"] = [masks.index(val) for val in masks]

        # Store the result in a class property for future use.
        self.filedict = filenames_dict

        return self

    def generate_dataset_dict(self, func=None, filedict=None, filters=True, **kwargs):
        """Generates a list of dictionaries using a user-defined annotation
        generator function on each image file/mask. The format is determined
        by the user defined function

        Parameters
        ----------
        func: function
            A user-defined function that operates on a set of images and a mask
            file to generate a dictionary of annotations. The DataLoader
            expects this function to take in kwargs as follows
            (image_files, mask_file, **kwargs), where image files is a list of
            paths to image filenames (each image corresponds to one band) and
            mask_file points to a single mask filename.
        filedict: dict
            A dictionary with image and mask filepaths defined, generated by
            `DataLoader.generate_filedict`. If not specified, attempts to use
            a filedict stored within the `DataLoader` instance.
        filters: bool
            Determines whether the list of filters is passed along to the
            annotation function. If true is passed along as
            (images, mask, index, filters, other kwargs).

        Returns
        -------
        self : DataLoader
            A DataLoader with a dataset dictionary generated. Access using
            `DataLoader.get_dataset()`.
        """

        if func is None:
            raise ValueError(
                "No annotation function has been provided. Please supply a function that takes in arguments: (image_files, mask_file, index, and optionally filters)."
            )
        if filedict is None:
            if self.filedict is None:
                raise ValueError("No file dictionary has been provided.")
            else:
                filedict = self.filedict

        # Group images by filter
        img_files = np.transpose([filedict[filt]["img"] for filt in filedict["filters"]])

        # Initialize data dictionary
        dataset_dicts = []

        # Use user-provided function to generate a dictionary record per image set
        for images, mask, index in zip(img_files, filedict["mask"], filedict["index"]):
            # pass along filter list if requested
            if filters:
                record = func(images, mask, index, filedict["filters"], **kwargs)
            else:
                record = func(images, mask, index, **kwargs)

            # Add records to the data_dict
            dataset_dicts.append(record)

        self.dataset = dataset_dicts
        return self

    def load_coco_json_file(self, file):
        """Open a JSON text file, and return encoded data as dictionary.

        Assumes JSON data is in the COCO format.

        Parameters
        ----------
        file : str
            pointer to file

        Returns
        -------
            dictionary of encoded data
        """
        self.dataset = get_data_from_json(file)

        return self

    def _verify_input_file_count(self, filenames_dict):
        """Make sure that there are the same number of images for each filter"""

        # Create dictionary of filter : file count for printing the exception
        # use a `set` to determine if there are actually different numbers of 
        # files per filter.
        num_files = set()
        file_counts = dict()
        for filt in filenames_dict["filters"]:
            file_counts[filt] = len(filenames_dict[filt]["img"])
            num_files.add(file_counts[filt])

        if len(num_files) > 1:
            raise RuntimeError(f"Found different number of files for each filter: {file_counts}")
            
            
    def random_sample(self,outdir,filedict=None,sets=['train','test'], nfiles=[3,1]):
        """Generates randomly sampled subsets of the data, assuming the scarlet output exists

        Parameters
        ----------
        outdir: str
            Base output directory
        filedict: dict
            Dictionary of files to be sampled
        sets: list[str]
            Name of subsets
        nfiles:
            How many files go in each subset
        
        """
        
        if filedict is None:
            if self.filedict is None:
                raise ValueError("No file dictionary has been provided.")
            else:
                filedict = self.filedict
                
        
        
        img_files = np.transpose([filedict[filt]["img"] for filt in filedict["filters"]])
        mask_files = np.transpose([filedict["mask"]])

        for i,dset in enumerate(sets):
            if not os.path.isdir(os.path.join(outdir,dset)):
                os.makedirs(os.path.join(outdir,dset))                

            allinds=range(len(img_files))
            inds=random.sample(allinds, nfiles[i])
            new_img_files = img_files[inds]
            new_mask_files = mask_files[inds]
            for imfs, maskfs in zip(new_img_files,new_mask_files):
                for imf in imfs:
                    shutil.copy(imf, os.path.join(os.path.join(outdir,dset),ntpath.basename(imf)))
                shutil.copy(maskfs[0], os.path.join(os.path.join(outdir,dset),ntpath.basename(maskfs[0])))
            img_files = np.array([img_files[j] for j in allinds if j not in inds])
            mask_files = np.array([mask_files[j] for j in allinds if j not in inds])

        
        return self


def get_data_from_json(filename):
    """Open a JSON text file, and return encoded data as dictionary.

    Parameters
    ----------
    filename : str
        The name of the file to load.

    Returns
    -------
        dictionary of encoded data

    Raises
    ------
    FileNotFoundError if the file cannot be found.
    """
    if not Path(filename).exists():
        raise FileNotFoundError(f"Unable to load file {filename}")

    # Opening JSON file
    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data



class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)


def convert_to_json(dict_list, output_file, allow_cached=True):
    """
    Converts dataset into COCO format and saves it to a json file.
    dataset_name must be registered in DatasetCatalog and in detectron2's standard format.

    Args:
        dict_list: list of metadata dictionaries
        output_file: path of json file that will be saved to
        allow_cached: if json file is already present then skip conversion
    """

    PathManager.mkdirs(os.path.dirname(output_file))
    with file_lock(output_file):
        if PathManager.exists(output_file) and allow_cached:
            logger.warning(
                f"Using previously cached COCO format annotations at '{output_file}'. "
                "You need to clear the cache file if your dataset has been modified."
            )
        else:
            print(f"Caching COCO format annotations at '{output_file}' ...")
            tmp_file = output_file + ".tmp"
            with PathManager.open(tmp_file, "w") as f:
                json.dump(dict_list, f,cls=NpEncoder)
            shutil.move(tmp_file, output_file)