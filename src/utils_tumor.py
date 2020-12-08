
# %%
# general
import os
import pandas as pd
import numpy as np
import json
import matplotlib.pyplot as plt
from tqdm import tqdm
from datetime import datetime
from datetime import date
import nrrd
from itertools import groupby

# deep learning
# The complete Fastai vision library
from fastai.vision import ImageList, get_transforms, imagenet_stats, ResizeMethod, cnn_learner, models, ClassificationInterpretation, ImageBBox, open_image, itertools, DatasetType


# metrics
from sklearn.metrics import accuracy_score, auc
from fastai.metrics import error_rate, accuracy, roc_curve, AUROC

# open images
from PIL import Image

# generate polygons:
from imantics import Polygons, Mask

# add the pyradiomics analysis
import radiomics
from radiomics import featureextractor

# Pillow repair?
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

# personal
if os.getcwd().__contains__('src'):
    from categories import make_categories, make_categories_advanced, cat_mapping_new, reverse_cat_list, malign_int, benign_int
else:
    from .categories import make_categories, make_categories_advanced, cat_mapping_new, reverse_cat_list, malign_int, benign_int

# %% Create Databunch functionality

# Constant definitions to avoid repetitions :
VALID_PART = 0.15
TEST_PART = 0.15
SEED = 53
np.random.seed(SEED)

F_KEY = 'FileName (png)'
CLASS_KEY = 'Aggressiv/Nicht-aggressiv'
ENTITY_KEY = 'Tumor.Entitaet'


def get_advanced_dis_df(df, mode=False):
    """
    redefine the dataframe distribution for advanced training -> separate by entities!
    """
    # 1. get number of entities in overall_df
    # 2. split entities according to train, val / test-split

    # init the empyt idx lists
    train_idx = []
    valid_idx = []
    test_idx = []

    # get the categories by which to split
    cats = reverse_cat_list

    for cat in cats:
        # get all matching df entries
        df_loc = df.loc[df[ENTITY_KEY] == cat]
        loclen = len(df_loc)

        # now split acc to the indices
        validlen = round(loclen * VALID_PART)
        testlen = round(loclen * TEST_PART)
        trainlen = loclen - validlen - testlen

        # get the matching indices and extend the idx list
        df_loc_train = df_loc.iloc[:trainlen]
        train_idx.extend(list(df_loc_train.index))

        df_loc_valid = df_loc.iloc[trainlen:trainlen+validlen]
        valid_idx.extend(list(df_loc_valid.index))

        df_loc_test = df_loc.iloc[trainlen+validlen::]
        test_idx.extend(list(df_loc_test.index))

    # summarize in dictionary
    dis = {
        'train': {
            'len': len(train_idx),
            'idx': train_idx,
        },
        'valid': {
            'len': len(valid_idx),
            'idx': valid_idx,
        },
        'test': {
            'len': len(test_idx),
            'idx': test_idx,
        }
    }

    if mode:
        dis = {
            'test_external': {
                'len': len(df),
                'idx': list(range(len(df))),
            }
        }

    return dis


def calculate_age(born, diag):
    """get the age from the calendar dates"""
    born = datetime.strptime(born, "%d.%m.%Y").date()
    diag = datetime.strptime(diag, "%d.%m.%Y").date()
    return diag.year - born.year


def apply_cat(train, valid, test, dis, new_name, new_cat):
    """add a new category to the dataframe"""
    train_idx = dis['train']['idx']
    valid_idx = dis['valid']['idx']
    test_idx = dis['test']['idx']

    train[new_name] = [new_cat[idx] for idx in train_idx]
    valid[new_name] = [new_cat[idx] for idx in valid_idx]
    test[new_name] = [new_cat[idx] for idx in test_idx]
    return train, valid, test


def get_df_dis(df, born_key='OrTBoard_Patient.GBDAT', diag_key='Erstdiagnosedatum',
               t_key='Tumor.Entitaet', pos_key='Befundlokalisation', out=True,
               mode=False):
    """
    extract ages and other information from df
    """

    # get ages
    if mode:
        ages = df['Alter bei Erstdiagnose']
    else:
        ages = [calculate_age(born, diag) for (born, diag) in zip(
            df[born_key], df[diag_key])]

    # get labels
    labels = [float(lab) for lab in df[CLASS_KEY]]

    # get male(0) / female(1)
    if mode:
        fm = [1 if d_loc == 'f' else 0 for d_loc in df['Geschlecht']]
    else:
        fm = [int(name[0] == 'F') for name in df[F_KEY]]

    # tumor_kind
    tumor_kind = df[t_key]

    # position
    position = df[pos_key]

    # get the shuffled indexes
    dis = get_advanced_dis_df(df, mode=mode)

    if out:
        for key in dis.keys():
            print(f"{key}:")
            print_info(ages, labels, fm, dis[key]['idx'], tumor_kind, position)

        print("All:")
        print_info(ages, labels, fm, list(
            range(len(ages))), tumor_kind, position)

    return ages


def print_info(ages, labels, fm, active_idx, tumor_kind, position, nums=1):
    """
    summarize all informations as a print message
    """

    age = np.array([ages[i] for i in active_idx]).mean().round(nums)
    age_std = np.array([ages[i]
                        for i in active_idx]).std().round(nums)
    print(f'Age: {age} ± {age_std}')

    females = np.array([fm[i] for i in active_idx]).sum()
    femals_p = round((100*females) / len(active_idx), nums)
    print(f'Female: {females} ({femals_p}%)')

    malign = int(np.array([labels[i] for i in active_idx]).sum())
    malign_p = round((100 * malign) / len(active_idx), nums)
    print(f'Malignancy: {malign} ({malign_p}%)')
    print(f'Benign: {len(active_idx)-malign} ({100-malign_p}%)')

    _, cat_mapping = make_categories_advanced(simple=False)

    tumor_list = list(cat_mapping.keys())

    for tumor in tumor_list:
        tums = [int(tumor == name)
                for name in tumor_kind[active_idx]]
        num_tums = np.array(tums).sum()
        per_tum = round(100 * num_tums / len(active_idx), nums)
        print(f'{tumor}: {num_tums} ({per_tum}%)')

    position_dict = {}
    position_dict['Torso/head'] = ['Becken',
                                   'Thoraxwand', 'Huefte', 'LWS', 'os sacrum']
    position_dict['Upper Extremity'] = [
        'Oberarm', 'Hand', 'Schulter', 'Unterarm']
    position_dict['Lower Extremity'] = [
        'Unterschenkel', 'Fuß', 'Knie', 'Oberschenkel']

    for pos_k in position_dict.keys():
        cur_pos = [int(p in position_dict[pos_k])
                   for p in position[active_idx]]
        num_pos = np.array(cur_pos).sum()
        per_pos = round(100 * num_pos / len(active_idx), nums)
        print(f'{pos_k}: {num_pos} ({per_pos}%)')

    dset_part = round(100 * len(active_idx) / len(ages), nums)
    print(f'Dataset Nums: {len(active_idx)} ({dset_part}%)\n\n')

# %% Interpret the results


def get_acc(interp):
    """
    get the accuracy of the current interp set, using scipy
    """
    return accuracy_score(interp.y_true, interp.pred_class)


def plot_roc_curve(interp, indx=1, lw=2, off=0.02):
    """
    draw the roc curve
    """
    x, y = roc_curve(interp.preds[:, indx], interp.y_true)
    auc_v = auc(x, y)
    plt.figure("roc-curve", figsize=(8,8))
    plt.plot(x, y, color='darkorange',
             label='ROC curve (area = %0.2f)' % auc_v)
    plt.grid(0.25)
    plt.plot([0, 1], [0, 1], color='navy', lw=lw, linestyle='--')
    plt.xlim([0.0-off, 1.0])
    plt.ylim([0.0, 1.0 + off])
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('Receiver operating characteristic')
    plt.legend(loc="lower right")

# %% Segmentation: Create the bounding boxes

def add_bb_2_csv(csv_path, seg_path, pic_path, crop_path, fac=1, crop=True, mode=False):
    """
    construct the bounding boxes and add them to the csv file
    """
    # open csv
    if mode:
        df = pd.read_excel(csv_path)
    else:
        df = pd.read_csv(csv_path, header='infer', delimiter=';')

    len_df = len(df)

    # predefine arrays
    top, left, bottom, right = np.empty([len_df]), np.empty(
        [len_df]), np.empty([len_df]), np.empty([len_df])

    # iterate trough the files:
    for i, (file, label) in tqdm(enumerate(zip(df[F_KEY], df[CLASS_KEY]))):

        # paths:
        imfile = os.path.join(pic_path, f'{file}.png')
        segname = format_seg_names(file)
        segfile = os.path.join(seg_path, f'{segname}.seg.nrrd')

        try:
            # get the bounding box
            top[i], left[i], bottom[i], right[i] = nrrd_2_bbox(
                segfile, imfile, fac, title=str(label))
        except:
            print(segfile)

    # add the bounding boxes to the dataframe
    df['top'] = top
    df['left'] = left
    df['bottom'] = bottom
    df['right'] = right

    # save to csv!
    if mode:
        df.to_excel(csv_path)
    else:
        df.to_csv(csv_path, sep=';', index=False)

    return df


def add_classes_to_csv(csv_path, mode=False):
    """
    construct the bounding boxes and add them to the csv file
    """
    # open csv
    if mode:
        df = pd.read_excel(csv_path)
    else:
        df = pd.read_csv(csv_path, header='infer', delimiter=';')

    len_df = len(df)

    # predefine arrays
    agg_non_agg, ben_loc_mal, clinicla_flow, clinicla_flow_red, super_ent = np.empty([len_df]), np.empty(
        [len_df]), np.empty([len_df]), np.empty([len_df]), np.empty([len_df])

    # iterate trough the files:
    for i, label in tqdm(enumerate(df[ENTITY_KEY])):
        agg_non_agg[i] = cat_mapping_new[label][1]
        ben_loc_mal[i] = cat_mapping_new[label][2]
        clinicla_flow[i] = cat_mapping_new[label][3]
        clinicla_flow_red[i] = cat_mapping_new[label][4]
        super_ent[i] = cat_mapping_new[label][6]
    
    benmal_info = [] 
    for loc_ent in df[ENTITY_KEY]:
        ent_int = cat_mapping_new[loc_ent][0]
        benmal = 1 if ent_int in malign_int else 0
        benmal_info.append(benmal)

    # add the bounding boxes to the dataframe
    df[CLASS_KEY] = benmal_info  
    df['Aggressive - Non Aggressive'] = agg_non_agg
    df['Benigne - Local Aggressive - Maligne'] = ben_loc_mal
    df['Grade of clinical workflow'] = clinicla_flow
    df['Grade for clinical workflow (2 + 3 = 2 > assessment in MSK center needed)'] = clinicla_flow_red
    df['Super Entity (chon: 0, osteo:1, meta:2, other:3)'] = super_ent

    # save to csv!
    if mode:
        df.to_excel(csv_path)
    else:
        df.to_csv(csv_path, sep=';', index=False)

    return df


def nrrd_2_bbox(nrrd_path, im_path, fac,
                title='tumor', show=False,
                nrrd_key='Segmentation_ReferenceImageExtentOffset'):
    """
    generate a boundingbox from the nrrd file
    """
    # 1. open nrrd image:
    readdata, header = nrrd.read(nrrd_path)
    nrrd_img = np.transpose(readdata[:, :, 0] * 255)
    nrrd_shape = nrrd_img.shape
    height, width = nrrd_shape[0], nrrd_shape[1]

    # 2. open img
    img = open_image(im_path)

    # 3. get the offsets from the nrrd file
    offset = header[nrrd_key].split()
    offset = [int(off) for off in offset]
    offset = offset[0:2]

    # define the factored lenghts
    diff_width = (width * (fac-1)) / 2
    diff_height = (height * (fac-1)) / 2

    # define the bounding box sizes
    top = offset[1] - diff_height
    left = offset[0] - diff_width
    bottom = offset[1] + height + diff_height
    right = offset[0] + width + diff_width

    if show:
        bbox = ImageBBox.create(
            *img.size, [[top, left, bottom, right]], labels=[0], classes=[title])
        img.show(y=bbox, figsize=(14, 14))

    # return the bounding box:
    return int(top), int(left), int(bottom), int(right)


def nrrd_2_mask(nrrd_path, im_path, title='tumor', nrrd_key='Segmentation_ReferenceImageExtentOffset', fac=20, as_array=False):
    """
    generate mask from the nrrd file
    """
    # load nrrd image
    readdata, header = nrrd.read(nrrd_path)
    nrrd_img = np.transpose(readdata[:, :, 0] * fac)

    # get the offsets
    offset = header[nrrd_key].split()
    offset = [int(off) for off in offset]
    offset = offset[0:2]

    # load true image
    background = Image.open(im_path)
    foreground = Image.fromarray(nrrd_img)

    # generate masked image
    mask = Image.fromarray(np.array(background) * 0)
    mask.paste(foreground, offset, foreground)

    return np.array(mask)[:, :, 0] if as_array else mask


def format_seg_names(name):
    """replace 'ö','ä','ü',',',' '  """
    name = name if name[-1] != ' ' else name[:-1]
    name = name.replace('ö', 'oe').replace('Ö', 'OE')
    name = name.replace('ä', 'ae').replace('Ä', 'AE')
    name = name.replace('ü', 'ue').replace('Ü', 'UE')
    name = name.replace(',', '')
    return name


def generate_masks(df, nrrd_path, pic_path, mask_path, gen_rad=True):
    """
    save all pictures in a masked version in the mask_folder
    """

    for file in tqdm(df[F_KEY]):
        # get names
        pic_name = os.path.join(pic_path, f'{file}.png')
        file = format_seg_names(file)
        nrrd_name = os.path.join(nrrd_path, f'{file}.seg.nrrd')

        # mask the picture
        try:
            mask = nrrd_2_mask(nrrd_name, pic_name, fac=255)

            # save masked picture:
            mask_name = os.path.join(mask_path, f'{file}.png')
            mask.save(mask_name)

            if gen_rad:
                mask = np.array(mask)
                sh = mask.shape
                mask = mask.reshape((sh[2], sh[1], sh[0]))
                nrrd.write(f'../radiomics/label/{file}.nrrd', mask)
        except:
            print(nrrd_name)

# %% coco-formatting


def make_empty_coco(mode='train', simple=True):
    des = f'{mode}-BoneTumor detection in coco-format'
    today = date.today()
    today_str = str(today.year) + str(today.month) + str(today.day)
    cat_list, cat_mapping = make_categories_advanced(simple)

    coco = {
        "infos": {
            "description": des,
            "version": "0.01",
            "year": today.year,
            "contributor": "Nikolas Wilhelm",
            "date_created": today_str
        },
        "licences": [
            {
                "id": 1,
                "name": "todo"
            },
        ],
        "categories": cat_list,
        "images": [],
        "annotations": [],
    }
    return coco, cat_mapping


def get_cocos_from_df(df, paths, save=True, seg=True, simple=True, newmode=0, ex_mode=False):
    """
    build the coco dictionaries from the dataframe
    """
    # get the shuffled indexes
    dis = get_advanced_dis_df(df, mode=ex_mode)

    # the list of coco dictionaries
    cocos = []

    for i, mode in enumerate(dis.keys()):
        # get the active indices
        indices = dis[mode]['idx']

        # make empty coco_dict
        cocos.append(make_coco(df, mode, indices, seg=seg, newmode=newmode,
                               simple=simple, path=paths["pic"], path_nrd=paths["seg"]))

        if save:
            local_path = os.getcwd()
            add = "../" if local_path[-3:] == "src" else ""

            save_file = f'{add}{mode}.json'
            print(f'Saving to: {save_file}')
            with open(save_file, 'w') as fp:
                json.dump(cocos[i], fp, indent=2)

    return cocos


def make_coco(df, mode, idxs, seg=False, path='../PNG2', path_nrd='../SEG', simple=True, newmode=0):
    # create the empty coco format
    coco, cat_mapping = make_empty_coco(mode, simple=simple)

    # go trough all indexes and append the img-names and annotations
    for idx in idxs:

        # get the current object
        o = df.iloc[idx]

        # get the filename
        file = o[F_KEY]
        filename = file + '.png'

        # get height and width by loading the picture
        filepath = os.path.join(path, filename)
        img_s = np.array(Image.open(filepath)).shape
        height, width = img_s[0], img_s[1]

        # get the image id -> idx should be unique
        id_tumor = int(idx)

        # get the bounding box
        bbox = tlbr2bbox(o['top'], o['left'], o['bottom'], o['right'])

        # create the simple poly:
        poly = [
            (o['left'], o['top']), (o['right'], o['top']),
            (o['right'], o['bottom']), (o['left'], o['bottom']),
        ]
        poly = list(itertools.chain.from_iterable(poly))
        poly = [int(p) for p in poly]

        # get the class:
        name = o[CLASS_KEY] if simple else o[ENTITY_KEY]

        cat = cat_mapping[name]

        if newmode > 0:
            cat = cat_mapping_new[name][newmode]

        # build the image dictionary
        img_dict = {
            "id": id_tumor,
            "file_name": filename,
            "height": height,
            "width": width,
        }

        # build the annotation dictionary
        ann_dict = {
            "id": id_tumor,
            "image_id": id_tumor,
            "category_id": cat,
            "iscrowd": 0,
            "area": int(height * width),
            "bbox": bbox,
            "segmentation": [poly],
        }

        # get the segmentation if required
        if seg:
            segname = format_seg_names(file)
            # get the rle - mask
            nrrdpath = os.path.join(path_nrd, segname + '.seg.nrrd')
            mask = nrrd_2_mask(nrrdpath, filepath, as_array=True)
            polygons = Mask(mask).polygons()

            ann_dict["area"] = int(np.sum(mask > 0))
            ann_dict["segmentation"] = check_seg(polygons.segmentation)

        # append the dictionaries to the coco bunch
        coco['images'].append(img_dict)
        coco['annotations'].append(ann_dict)

    return coco


def check_seg(segl):
    """check the segmentation format"""
    checked = segl.copy()

    # take the longest if we have multiple polygons ..?
    if len(segl) > 1:
        maxlen = 0
        for loc_seg in segl:
            if len(loc_seg) > maxlen:
                maxlen = len(loc_seg)
                checked = loc_seg

    return checked


def tlbr2bbox(top, left, bottom, right, op=int):
    """
    tlbr = [top, left, bottom, right]
    to ->
    bbox = [x(left), y(top), width, height]
    """
    x = op(left)
    y = op(top)
    width = op(right - left)
    height = op(bottom - top)

    return [x, y, width, height]


def binary_mask_to_rle(binary_mask):
    """
    from: https://stackoverflow.com/questions/49494337/encode-numpy-array-using-uncompressed-rle-for-coco-dataset
    """
    rle = {'counts': [], 'size': list(binary_mask.shape)}
    counts = rle.get('counts')
    for i, (value, elements) in enumerate(groupby(binary_mask.ravel(order='F'))):
        if i == 0 and value == 1:
            counts.append(0)
        counts.append(len(list(elements)))
    return rle


def get_df_paths(mode=False):
    """
    collect dataframe and all relevant paths:
    """
    # get working directory path
    path = os.getcwd()

    add = "../" if path[-3:] == "src" else ""

    name = 'datainfo'
    pic_folder = 'PNG2'
    crop_folder = 'CROP'
    seg_folder = 'SEG'
    mask_folder = 'MASK'

    if mode:
        name = f'{name}_external'
        pic_folder = f'{pic_folder}_external'
        seg_folder = f'{seg_folder}_external'

    name = f'{name}.xlsx' if mode else f'{name}.csv'

    # get all releevant paths
    paths = {
        "csv": os.path.join(path, f'{add}{name}'),
        "pic": os.path.join(path, f'{add}{pic_folder}'),
        "seg": os.path.join(path, f'{add}{seg_folder}'),
        "crop": os.path.join(path, f'{add}{crop_folder}'),
        "mask": os.path.join(path, f'{add}{mask_folder}'),
        "nrrd": os.path.join(path, f'{add}/radiomics/image')
    }

    # get df
    if mode:
        df = pd.read_excel(paths["csv"])
    else:
        df = pd.read_csv(paths["csv"], header='infer', delimiter=';')

    return df, paths


def regenerate_ex_names(paths, new_path='../PNG_external'):
    """"""
    # append idlist
    df = pd.read_excel(paths["csv"])
    idlist = np.array(list(range(1, len(df)+1)))
    np.random.shuffle(idlist)
    df['id'] = idlist
    df.to_excel(paths["csv"])

    df = pd.read_excel(paths["csv"])
    old_path = paths['pic']
    for id, fname in zip(df['id'], df[F_KEY]):
        filename = f'{old_path}/{fname}.png'
        img = Image.open(filename)
        filename_new = f'{new_path}/{id}.png'
        img.save(filename_new)


# %% Perform dataset preparation
if __name__ == '__main__':
    simple = True

    for external_mode in [False, True]:
        # get the paths
        df, paths = get_df_paths(mode=external_mode)

        # %% show the distributions
        print('\n\nDataset information:\n')
        ages = get_df_dis(df, mode=external_mode)

        # %% generate the cropped pictures in the crop folder
        print('\n\nAdd the bounding box to the csv:')
        add_bb_2_csv(paths["csv"], paths["seg"],
                     paths["pic"], paths["crop"], fac=1.0, mode=external_mode)

        # %% add the detailed classes to the dataframe
        print('\n\nAdd the detailed classes to the csv')
        add_classes_to_csv(paths["csv"], mode=external_mode)

        # %% build the coco-formated json
        print('\n\nTransform to coco format')
        cocos = get_cocos_from_df(df, paths, save=True,
                                  seg=True, simple=simple, newmode=0, ex_mode=external_mode)


# %%