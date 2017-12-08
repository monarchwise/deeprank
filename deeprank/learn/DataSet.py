import os
import sys
import h5py
from torch import FloatTensor
import torch.utils.data as data_utils
import subprocess as sp
import numpy as np

from deeprank.tools import sparse

try:
	from tqdm import tqdm
except:
	def tqdm(x):
		return x

class DataSet(data_utils.Dataset):

	'''
	Class that generates the data needed for deeprank.

	ARGUMENTS 
		
	data_folder : string

		the path of the folder where the numpy data are stored
		for each cconformation. This folder should contains N subfolder
		each subfolder that each contains and input and output subsbufolder
		The input subsubfolder should contain a file called AtomicDensities.npy
		The output subsubfolder should contain a file called score
		This hierarchie of folder can be created with the gendatatool.py 


	filter_dataset : None, integer or file name

		Int
		Maximum number of elements required in the data set.
		It might be that the data_folder contains N conformation
		but that we only want M of them. Then we can set dataset_size = M
		In that case we select M random comformation among the N

		File Name
		the file name must contains complex ID that are in the data_folder
		the data set will be only constucted from the cmplexes specified in
		the file.

		None (default value)
		all the data are loaded

	select_feature : dict or 'all'
		
		if 'all', all the .npy files contained in the input folder 
		will be loaded

		if a dict must be of the structure
		{name : [list of keys]} e.g. {AtomicDensities : ['CA','CB']}
		or
		{name : 'all'}     e.g {PSSM : 'all'}
		the name must correspond to a .pkl file generated by the grid tool
		and present in the input directory of the complex
		if the value is a list of keys only thoses keys will be loaded
		if 'all' all the data will be loaded

		The pkl files contains a dictionary. Each element has a key and corresponds 
		to a data of format Nx x Ny x Nz. Where Nx Ny Nz are the number of grid points
		on each axis. 


	select_target

		the name of the target we want. If target file is haddock.dat
		set select_target='haddock'

	normalize_x   :	Boolean

		normalize the values of the features or targets between 0 and 1


	USAGE

		data = DeepRankDataSet(folder_name)

	'''

	def __init__(self,data_folder,filter_dataset=None,
				 select_feature='all',select_target='binary_class',
		         normalize_features=False,normalize_targets=True):


		self.data_folder = data_folder
		self.filter_dataset = filter_dataset
		self.select_feature = select_feature
		self.select_target = select_target
		self.normalize_features = normalize_features
		self.normalize_targets = normalize_targets


		self.features = None
		self.targets  = None

		self.input_shape = None

		# load the data
		if os.path.isdir(data_folder):
			print('\n')
			print('='*40)
			print('=\t Build data set from folder')
			print('= \t %s' %data_folder)
			print('='*40,'\n')

	def __len__(self):
		return len(self.targets)

	def __getitem__(self,index):
		return self.features[index],self.targets[index]

	# load the dataset from a h5py file
	def load(self):

		fh5 = h5py.File(self.data_folder,'r')
		mol_names = list(fh5.keys())
		featgrp_name='mapped_features/'

		# get a subset
		if self.filter_dataset != None:

			# get a random subset if integers
			if isinstance(self.filter_dataset,int):
				np.random.shuffle(mol_names)
				mol_names = mol_names[:self.filter_dataset]

			# select based on name of file
			if os.path.isfile(self.filter_dataset):
				tmp_folder = []
				with open(self.filter_dataset) as f:
					for line in f:
						if len(line.split())>0:
							name = line.split()[0]
							tmp_folder += list(filter(lambda x: name in x,mol_names))
				f.close()
				mol_names = tmp_folder

		#	
		# load the data
		# the format of the features must be
		# Nconf x Nchanels x Nx x Ny x Nz
		# 
		# for each folder we create a tmp_feat of size Nchanels x Nx x Ny x Nz
		# that we then append to the feature list
		#
		features, targets = [], []
		for mol in tqdm(mol_names):

			# get the mol
			mol_data = fh5.get(mol)
			nx = mol_data['grid_points']['x'].shape[0]
			ny = mol_data['grid_points']['y'].shape[0]
			nz = mol_data['grid_points']['z'].shape[0]
			shape=(nx,ny,nz)

			# load all the features
			if self.select_feature == 'all':
				# loop through the features
				tmp_feat = []
				for feat_name, feat_members in mol_data.get(featgrp_name).items():
					# loop through all the feature keys
					for name,data in feat_members.items():
						if data.attrs['sparse']:
							spg = sparse.FLANgrid(sparse=True,
								                 index=data['index'].value,
								                 value=data['value'].value,
								                 shape=shape)
							tmp_feat.append(spg.to_dense())
						else:
							tmp_feat.append(data['value'].value)
				features.append(tmp_feat)

			# load selected features
			else:
				tmp_feat = []
				for feat_name,feat_channels in self.select_feature.items():

					# see if the feature exists
					feat_dict = mol_data.get(featgrp_name+feat_name)						
					
					if feat_dict is None:
						
						print('Error : Feature name %s not found in %s' %(feat_name,mol))
						opt_names = list(mol_data.get(featgrp_name).keys())
						print('Error : Possible features are \n\t%s' %'\n\t'.join(opt_names))
						sys.exit()

					# get the possible channels
					possible_channels = list(feat_dict.keys())

					# make sure that all the featchanels are in the file
					if feat_channels != 'all':
						for fc in feat_channels:
							if fc not in possible_channels:
								print("Error : required key %s for feature %s not in the database" %(fc,feat_name))
								print('Error : Possible features are \n\t%s' %'\n\t'.join(possible_channels))
								sys.exit()

					# load the feature channels
					for chanel_name,channel_data in feat_dict.items():
						if feat_channels == 'all' or chanel_name in feat_channels:
							if channel_data.attrs['sparse']:
								spg = sparse.FLANgrid(sparse=True,
									                  index=channel_data['index'].value,
									                  value=channel_data['value'].value,
									                  shape=shape)
								tmp_feat.append(spg.to_dense())
							else:
								tmp_feat.append(channel_data['value'].value)
							

				# append to the list of features
				features.append(np.array(tmp_feat))


			# target
			opt_names = list(mol_data.get('targets/').keys())			
			fname = list(filter(lambda x: self.select_target in x, opt_names))
			
			if len(fname) == 0:
				print('Error : Target name %s not found in %s' %(self.select_target,mol))
				print('Error : Possible targets are \n\t%s' %'\n\t'.join(opt_names))
				sys.exit()

			if len(fname)>1:
				print('Error : Multiple Targets Matching %s Found in %s' %(self.select_target,mol))
				print('Error : Possible targets are \n\t%s' %'\n\t'.join(opt_names))
				sys.exit()

			fname = fname[0]
			targ_data = mol_data.get('targets/'+fname)		
			targets.append(targ_data.value)

		# preprocess the data
		self.preprocess(features,targets)

		# close
		fh5.close()

	# put in torch format and normalize
	def preprocess(self,features,targets):

		# get the number of channels and points along each axis
		self.input_shape = features[0].shape

		# transform the data in torch Tensor
		self.features = FloatTensor(np.array(features))
		self.targets = FloatTensor(np.array(targets))

		# normalize the targets/featurs
		if self.normalize_targets:
			self.targets -= self.targets.min()
			self.targets /= self.targets.max()

		if self.normalize_features:
			for iC in range(self.features.shape[1]):
				self.features[:,iC,:,:,:] = (self.features[:,iC,:,:,:]-self.features[:,iC,:,:,:].mean())/self.features[:,iC,:,:,:].std()

	#convert the 3d data set to 2d data set
	def convert_dataset_to2d(self,proj2d=0):

		'''
		convert the 3D volumetric dataset to a 2D planar data set 
		to be used in 2d convolutional network
		proj2d specifies the dimension that we want to comsider as channel
		for example for proj2d = 0 the 2D images are in the yz plane and 
		the stack along the x dimension is considered as extra channels
		'''
		planes = ['yz','xz','xy']
		print(': Project 3D data set to 2D images in the %s plane ' %planes[proj2d])

		nf = self.__len__()
		nc,nx,ny,nz = self.input_shape
		if proj2d==0:
			self.features = self.features.view(nf,-1,1,ny,nz).squeeze()
		elif proj2d==1:
			self.features = self.features.view(nf,-1,nx,1,nz).squeeze()
		elif proj2d==2:
			self.features = self.features.view(nf,-1,nx,ny,1).squeeze()
		
		# get the number of channels and points along each axis
		# the input_shape is now a torch.Size object
		self.input_shape = self.features[0].shape




		