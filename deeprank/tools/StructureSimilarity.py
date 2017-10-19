import numpy as np
from deeprank.tools import transform, pdb2sql 
import sys,os

'''
Class to compute the
	L-RMS
	I-RMS
	Fnat
	DockQ score
of a decoy versus a ref
'''

class StructureSimilarity(object):

	def __init__(self,decoy,ref,verbose=False):
		self.decoy = decoy
		self.ref = ref
		self.verbose = verbose

	# compute the L-RMSD
	def compute_lrmsd(self,exportpath=None,method='svd'):

		'''
		Ref : DockQ: A Quality Measure for Protein-Protein Docking Models
		      http://journals.plos.org/plosone/article?id=10.1371/journal.pone.0161879
		L-RMSD is computed by aligning the longest chain of the decoy to the one of the  reference
		and computing the RMSD of the shortest chain between decoy and ref
		'''

		# create the sql
		sql_decoy = pdb2sql(self.decoy,sqlfile='decoy.db')
		sql_ref = pdb2sql(self.ref,sqlfile='ref.db')

		# extract the pos of chains A
		xyz_decoy_A = np.array(sql_decoy.get('x,y,z',chain='A'))
		xyz_ref_A = np.array(sql_ref.get('x,y,z',chain='A'))

		# extract the pos of chains B
		xyz_decoy_B = np.array(sql_decoy.get('x,y,z',chain='B'))
		xyz_ref_B = np.array(sql_ref.get('x,y,z',chain='B'))


		# check the lengthes
		if len(xyz_decoy_A) != len(xyz_ref_A):
			#print('Clean the xyz of chain A')
			xyz_decoy_A, xyz_ref_A = self.get_identical_atoms(sql_decoy,sql_ref,'A')

		if len(xyz_decoy_B) != len(xyz_ref_B):
			#print('Clean the xyz of chain B')
			xyz_decoy_B, xyz_ref_B = self.get_identical_atoms(sql_decoy,sql_ref,'B')
		

		# detect which chain is the longest
		nA,nB = len(xyz_decoy_A),len(xyz_decoy_B)
		if nA>nB:
			xyz_decoy_long = xyz_decoy_A
			xyz_ref_long = xyz_ref_A
			
			xyz_decoy_short = xyz_decoy_B
			xyz_ref_short = xyz_ref_B

		else:
			xyz_decoy_long = xyz_decoy_B
			xyz_ref_long = xyz_ref_B
			
			xyz_decoy_short = xyz_decoy_A
			xyz_ref_short = xyz_ref_A

		# get the translation so that both A chains are centered
		tr_decoy = self.get_trans_vect(xyz_decoy_long)
		tr_ref = self.get_trans_vect(xyz_ref_long)

		# translate everything for 1
		xyz_decoy_short = transform.translation(xyz_decoy_short,tr_decoy)
		xyz_decoy_long = transform.translation(xyz_decoy_long,tr_decoy)

		# translate everuthing for 2
		xyz_ref_short = transform.translation(xyz_ref_short,tr_ref)
		xyz_ref_long = transform.translation(xyz_ref_long,tr_ref)

		# get the ideql rotation matrix
		# to superimpose the A chains
		U = self.get_rotation_matrix(xyz_decoy_long,xyz_ref_long,method=method)

		# rotate the entire fragment
		xyz_decoy_short = transform.rotation_matrix(xyz_decoy_short,U,center=False)


		# compute the RMSD
		lrmsd =  self.get_rmsd(xyz_decoy_short,xyz_ref_short)

		# export the pdb for verifiactions
		if exportpath is not None:

			# extract the pos of the dimer
			xyz_decoy = np.array(sql_decoy.get('x,y,z'))
			xyz_ref = np.array(sql_ref.get('x,y,z'))

			# translate
			xyz_ref = transform.translation(xyz_ref,tr_ref)
			xyz_decoy = transform.translation(xyz_decoy,tr_decoy)
			
			# rotate decoy
			xyz_decoy= transform.rotation_matrix(xyz_decoy,U,center=False)

			# update the sql database
			sql_decoy.update_xyz(xyz_decoy)
			sql_ref.update_xyz(xyz_ref)		

			# export
			sql_decoy.exportpdb(exportpath+'/lrmsd_decoy.pdb')
			sql_ref.exportpdb(exportpath+'/lrmsd_aligned.pdb')

		# close the db
		sql_decoy.close()
		sql_ref.close()

		return lrmsd

	

	# compute the irmsd
	# we get here the contact of the REFs
	# and align the contact of the DECOY to it
	def compute_irmsd(self,cutoff=10,exportpath=None,method='svd'):

		'''
		Ref : DockQ: A Quality Measure for Protein-Protein Docking Models
		      http://journals.plos.org/plosone/article?id=10.1371/journal.pone.0161879
		i-RMSD is computed selecting the back bone of the contact residue with a cutoff of 10A
		in the decoy. Align these as best as possible with their coutner part in the ref
		and and compute the RMSD
		'''

		# create thes sql
		sql_decoy = pdb2sql(self.decoy,sqlfile='mol1.db')
		sql_ref = pdb2sql(self.ref,sqlfile='mol2.db')

		# get the contact atoms
		contact_ref = sql_ref.get_contact_atoms(cutoff=cutoff,extend_to_residue=True,only_backbone_atoms=True)

		# make a single list
		index_contact_ref = contact_ref[0]+contact_ref[1]


		# get the xyz and atom identifier of the decoy contact atoms
		xyz_contact_ref = sql_ref.get('x,y,z',index=index_contact_ref)
		data_contact_ref = sql_ref.get('chainID,resSeq,resName,name',index=index_contact_ref)

		# get the xyz and atom indeitifier of the reference
		xyz_decoy = sql_decoy.get('x,y,z')
		data_decoy = sql_decoy.get('chainID,resSeq,resName,name')

		# loop through the ref label
		# check if the atom is in the decoy
		# if yes -> add xyz to xyz_contact_decoy
		# if no  -> remove the corresponding to xyz_contact_ref
		xyz_contact_decoy = []
		index_contact_decoy = []
		clean_ref = False
		for iat,atom in enumerate(data_contact_ref):

			try:
				index = data_decoy.index(atom)
				index_contact_decoy.append(index)
				xyz_contact_decoy.append(xyz_decoy[index])
			except:
				#print('Warning CHAIN %s RES %d RESNAME %s ATOM %s not found in reference' %(atom[0],atom[1],atom[2],atom[3]))
				xyz_contact_ref[iat] = None
				index_contact_ref[iat] = None
				clean_ref = True

		# clean the xyz
		if clean_ref:
			xyz_contact_ref = [xyz for xyz in xyz_contact_ref if xyz is not None]
			index_contact_ref = [ind for ind in index_contact_ref if ind is not None]

		# check that we still have atoms in both chains
		chain_decoy = list(set(sql_decoy.get('chainID',index=index_contact_decoy)))
		chain_ref   = list(set(sql_ref.get('chainID',index=index_contact_ref)))
		error = 1
		if len(chain_decoy)<2:
			if self.verbose:
				print('Error in i-rmsd: only one chain represented in contact atoms of the decoy')
			error = -1
		if len(chain_ref)<2:
			if self.verbose:
				print('Error in i-rmsd: only one chain represented in contact atoms of the ref')
			error = -1

		# get the translation so that both A chains are centered
		tr_decoy = self.get_trans_vect(xyz_contact_decoy)
		tr_ref   = self.get_trans_vect(xyz_contact_ref)

		# translate everything 
		xyz_contact_decoy = transform.translation(xyz_contact_decoy,tr_decoy)
		xyz_contact_ref   = transform.translation(xyz_contact_ref,tr_ref)

		# get the ideql rotation matrix
		# to superimpose the A chains
		U = self.get_rotation_matrix(xyz_contact_decoy,xyz_contact_ref,method=method)

		# rotate the entire fragment
		xyz_contact_decoy = transform.rotation_matrix(xyz_contact_decoy,U,center=False)

		# compute the RMSD
		irmsd = error * self.get_rmsd(xyz_contact_decoy,xyz_contact_ref)

		# export the pdb for verifiactions
		if exportpath is not None:

			# update the sql database
			sql_decoy.update_xyz(xyz_contact_decoy,index=index_contact_decoy)
			sql_ref.update_xyz(xyz_contact_ref,index=index_contact_ref)

			sql_decoy.exportpdb(exportpath+'/irmsd_decoy.pdb',index=index_contact_decoy)
			sql_ref.exportpdb(exportpath+'/irmsd_ref.pdb',index=index_contact_ref)

		# close the db
		sql_decoy.close()
		sql_ref.close()

		return irmsd


	# compute only Fnat
	def compute_Fnat(self,cutoff=5.0):

		# create the sql
		sql_decoy = pdb2sql(self.decoy,sqlfile='mol1.db')
		sql_ref = pdb2sql(self.ref,sqlfile='mol2.db')

		# get the contact atoms
		residue_pairs_decoy = sql_decoy.get_contact_residue(cutoff=cutoff,return_contact_pairs=True,excludeH=True)
		residue_pairs_ref   = sql_ref.get_contact_residue(cutoff=cutoff,return_contact_pairs=True,excludeH=True)


		# form the pair data
		data_pair_decoy = []
		for resA,resB_list in residue_pairs_decoy.items():
			data_pair_decoy += [  (resA,resB) for resB in resB_list   ]

		# form the pair data
		data_pair_ref = []
		for resA,resB_list in residue_pairs_ref.items():
			data_pair_ref += [  (resA,resB) for resB in resB_list     ]


		# find the umber of residue that ref and decoys hace in common
		nCommon = len(set(data_pair_ref).intersection(data_pair_decoy))

		# normalize
		Fnat = nCommon/len(data_pair_ref)

		sql_decoy.close()
		sql_ref.close()

		return Fnat



	@staticmethod
	def compute_DockQScore(Fnat,lrmsd,irmsd,d1=8.5,d2=1.5):

		def scale_rms(rms,d):
			return(1./(1+(rms/d)**2))

		return 1./3 * (  Fnat + scale_rms(lrmsd,d1) + scale_rms(irmsd,d2) ) 


	@staticmethod
	def get_identical_atoms(db1,db2,chain):

		# get data
		data1 = db1.get('chainID,resSeq,name',chain=chain)
		data2 = db2.get('chainID,resSeq,name',chain=chain)

		# tuplify
		data1 = [tuple(d1) for d1 in data1]
		data2 = [tuple(d2) for d2 in data2]

		# get the intersection
		shared_data = list(set(data1).intersection(data2))

		# get the xyz
		xyz1,xyz2 = [],[]
		for data in shared_data:
			query = 'SELECT x,y,z from ATOM WHERE chainID=? AND resSeq=? and name=?'
			xyz1.append(list(list(db1.c.execute(query,data))[0]))
			xyz2.append(list(list(db2.c.execute(query,data))[0]))

		return xyz1,xyz2


	@staticmethod 
	def get_rmsd(P,Q):
		n = len(P)
		return np.sqrt(1./n*np.sum((P-Q)**2))


	
	def align_Kabsch(self,P,Q):

		# translate the points
		P = transform.translation(P,get_trans_vect(P))
		Q = transform.translation(Q,get_trans_vect(Q))

		# get the matrix
		U = self.get_rotation_matrix_Kabsh(P,Q)

		# form the new ones
		P = np.dot(U,P.T).T

		return P,Q

	
	def align_quaternion(self,P,Q):

		# translate the points
		P = transform.translation(P,get_trans_vect(P))
		Q = transform.translation(Q,get_trans_vect(Q))

		# get the matrix
		U = self.get_rotation_matrix_quaternion(P,Q)

		# form the new ones
		P = np.dot(U,P.T).T

		return P,Q

	@staticmethod 
	def get_trans_vect(P):
		return  -np.mean(P,0)


	
	def get_rotation_matrix(self,P,Q,method='svd'):

		# get the matrix with Kabsh method
		if method.lower()=='svd':
			return self.get_rotation_matrix_Kabsh(P,Q)

		# or with the quaternion method
		elif method.lower()=='quaternion':
			return self.get_rotation_matrix_quaternion(P,Q)

		else:
			raise ValueError('%s is not a valid method for rmsd alignement.\n Options are svd or quaternions' %method)

	@staticmethod 		
	def get_rotation_matrix_Kabsh(P,Q):

		'''
		based on
		[1] Molecular Distance Measure
		    https://cnx.org/contents/HV-RsdwL@23/Molecular-Distance-Measures
		'''

		pshape = P.shape
		qshape = Q.shape

		if pshape[0] == qshape[0]:
			npts = pshape[0]
		else:
			raise ValueError("Matrix don't have the same number of points",P.shape,Q.shape)
			


		p0,q0 = np.abs(np.mean(P,0)),np.abs(np.mean(Q,0))
		eps = 1E-6
		if any(p0 > eps) or any(q0 > eps):
			raise ValueError('You must center the fragment first',p0,q0)


		# form the covariance matrix
		A = np.dot(P.T,Q)/npts

		# SVD the matrix
		V,S,W = np.linalg.svd(A)

		# the W matrix returned here is
		# already its transpose
		# https://docs.scipy.org/doc/numpy-1.13.0/reference/generated/numpy.linalg.svd.html
		W = W.T

		# determinant 
		d = np.linalg.det(np.dot(W,V.T))

		# form the U matrix
		Id = np.eye(3)
		if d < 0:
			Id[2,2] = -1

		U = np.dot(W,np.dot(Id,V.T))

		return U

	@staticmethod
	def get_rotation_matrix_quaternion(P,Q):

		'''
		based on 
		[1] Using quaternions to calculate RMSD
		    http://www.ams.stonybrook.edu/~coutsias/papers/rmsd17.pdf
		'''

		pshape = P.shape
		qshape = Q.shape

		if pshape[0] == qshape[0]:
			npts = pshape[0]
		else:
			raise ValueError("Matrix don't have the same number of points",P.shape,Q.shape)

		p0,q0 = np.abs(np.mean(P,0)),np.abs(np.mean(Q,0))
		eps = 1E-6
		if any(p0 > eps) or any(q0 > eps):
			raise ValueError('You must center the fragment first',p0,q0)

		# form the correlation matrix
		R = np.dot(P.T,Q)

		# form the F matrix (eq. 10 of ref[1])		
		F = np.zeros((4,4))

		F[0,0] = np.trace(R)
		F[0,1] = R[1,2]-R[2,1]
		F[0,2] = R[2,0]-R[0,2]
		F[0,3] = R[0,1]-R[1,0]

		F[1,0] = R[1,2]-R[2,1] 
		F[1,1] = R[0,0]-R[1,1]-R[2,2]
		F[1,2] = R[0,1]+R[1,0]
		F[1,3] = R[0,2]+R[2,0]

		F[2,0] = R[2,0]-R[0,2]
		F[2,1] = R[0,1]+R[1,0]
		F[2,2] =-R[0,0]+R[1,1]-R[2,2]
		F[2,3] = R[1,2]+R[2,1]

		F[3,0] = R[0,1]-R[1,0]
		F[3,1] = R[0,2]+R[2,0]
		F[3,2] = R[1,2]+R[2,1]
		F[3,3] =-R[0,0]-R[1,1]+R[2,2]

		# diagonalize it
		l,U = np.linalg.eig(F)

		# extract the eigenvect of the highest eigenvalues
		indmax = np.argmax(l)
		q0,q1,q2,q3 = U[:,indmax]

		# form the rotation matrix (eq. 33 ref[1])
		U = np.zeros((3,3))

		U[0,0] = q0**2+q1**2-q2**2-q3**2
		U[0,1] = 2*(q1*q2-q0*q3)
		U[0,2] = 2*(q1*q3+q0*q2)
		U[1,1] = 2*(q1*q2+q0*q3)
		U[1,2] = q0**2-q1**2+q2*2-q3**2
		U[1,2] = 2*(q2*q3-q0*q1)
		U[2,0] = 2*(q1*q3-q0*q2)
		U[2,1] = 2*(q2*q3+q0*q1)
		U[2,2] = q0**2-q1**2-q2**2+q3**2

		return U

#####################################################################################
#
#	THE MAIN FUNCTION CALLED IN THE INTERNAL TARGET CALCULATOR
#
#####################################################################################

def __compute_target__(decoy,outdir='./'):

	mol_name = decoy.split('/')[-1][:-4]
	export_file = outdir + '/' + mol_name

	# get the reference
	ref = os.path.dirname(os.path.realpath(decoy)) + '/ref.pdb'

	# if the two files are the same and contains the same data
	# we have a native file
	if os.path.getsize(decoy) == os.path.getize(ref):
		if open(decoy,'r').read() == open(ref,'r').read():

			# lrmsd = irmsd = 0 | fnat = dockq = 1
			np.savetxt(export_file+'.LRMSD',[0.0])
			np.savetxt(export_file+'.IRMSD',[0.0])
			np.savetxt(export_file+'.FNAT',[1.0])
			np.savetxt(export_file+'.DOCKQ',[1.0])

	# or it's a decoy
	else:

		# init the class
		sim = StructureSimilarity(decoy,ref)

		lrmsd = sim.compute_lrmsd()
		np.savetxt(export_file+'.LRMSD',[lrmsd])

		irmsd = sim.compute_irmsd()
		np.savetxt(export_file+'.IRMSD',[irmsd])

		Fnat = sim.compute_Fnat()
		np.savetxt(export_file+'.FNAT',[Fnat])

		dockQ = sim.compute_DockQScore(Fnat,lrmsd,irmsd)
		np.savetxt(export_file+'.DOCKQ',[dockQ])


if __name__ == '__main__':

	#test_points()
	import time
	BM4 = '/home/nico/Documents/projects/deeprank/data/HADDOCK/BM4_dimers/'
	decoy = BM4 + 'decoys_pdbFLs/1AK4/water/1AK4_3w.pdb'
	ref = BM4 + 'BM4_dimers_bound/pdbFLs_ori/1AK4.pdb'

	#CAPRI = '/home/nico/Documents/projects/deeprank/data/CAPRI/'
	#decoy = CAPRI + 'T29/complex_0024.pdb'
	#decoy = CAPRI + 'T29/2vdu_chainFD.pdb'
	#ref = CAPRI + 'T29/2vdu_chainEB.pdb'

	sim = StructureSimilarity(decoy,ref)

	t0 = time.time()
	lrmsd_svd = sim.compute_lrmsd(exportpath='./',method='svd')
	t1 = time.time()-t0

	t0 = time.time()
	lrmsd_quat = sim.compute_lrmsd(exportpath='./',method='quaternion')
	t2 = time.time()-t0

	print('LRMSD TIME %f (svd) %f (quat)' %(t1,t2))

	time.time()
	irmsd_svd = sim.compute_irmsd(exportpath='./',method='svd')
	t1 = time.time()-t0

	t0= time.time()
	irmsd_quat = sim.compute_irmsd(exportpath='./',method='quaternion')
	t2 = time.time()-t0

	print('IRMSD TIME %f (svd) %f (quat)' %(t1,t2))

	Fnat = sim.compute_Fnat()
	dockQ = sim.compute_DockQScore(Fnat,lrmsd_svd,irmsd_svd)

	print('L-RMSD = ', lrmsd_svd, lrmsd_quat )
	print('I-RMSD = ', irmsd_svd, irmsd_quat )
	print('Fnat   = ', Fnat  )
	print('DockQ  = ', dockQ )