import pandas            as pd
import numpy             as np

from sklearn.preprocessing      import LabelEncoder
from sklearn.preprocessing      import MinMaxScaler
from sklearn.preprocessing      import minmax_scale
from sklearn.preprocessing      import MaxAbsScaler
from sklearn.preprocessing      import StandardScaler
from sklearn.preprocessing      import RobustScaler
from sklearn.preprocessing      import Normalizer
from sklearn.preprocessing.data import QuantileTransformer

import json
import torch
import torch.optim

FLOAT_COLUMNS = [ 'price', 'longitude', 'latitude', 'total_square', 'living_square', 'kitchen_square', 'distance_from_metro']
INT_COLUMNS   = [ 'number_of_rooms', 'floor_number', 'number_of_floors', 'exploitation_start_year' ]
STR_COLUMNS   = [ 'type', 'bulding_type' ]
TARGET_COLUMN =   'price'

def check_float( x ):
	try:
		float(x)
	except ValueError:
		return False
	return True

def check_row( row ):
	check_float_s = check_float( row.longitude ) and check_float( row.latitude )
	for columnName in (FLOAT_COLUMNS + INT_COLUMNS):
		if columnName in row : check_float_s = check_float_s and check_float( row[ columnName ] )

	return check_float_s

class QuantileRegressionLoss( torch.nn.Module ):
	def __init__(self, q):
		super(QuantileRegressionLoss,self).__init__()
		self.q = q
	def forward(self, predict, target):
		e = ( target- predict )
		result = torch.mean( torch.max( self.q*e, (self.q-1)*e ))
		return result

def limitDataUsingLimitsFromFilename( dataFrame, limitsFileName ) :
	limitsData = dict()
	with open( limitsFileName ) as f:
		limitsData = json.load(f)
	
	mask = True
	for columnName in limitsData.keys() :
		MIN_VALUE = limitsData[ columnName ]['min']
		MAX_VALUE = limitsData[ columnName ]['max']
		
		mask = (dataFrame[ columnName ] >= MIN_VALUE ) & mask
		mask = (dataFrame[ columnName ] <= MAX_VALUE ) & mask
	
	dataFrame = dataFrame[ mask ]
	
	dataFrame.drop(labels=['kitchen_square','living_square','floor_number'], axis=1, inplace=True)
	if 'id' in dataFrame.columns : dataFrame.drop(labels=['id',], axis=1, inplace=True )	
	
	return dataFrame

# Neural network models	
class LinearNet(torch.nn.Module):
	def __init__(self, in_size ):
		super( LinearNet, self).__init__()
		self.fc1 = torch.nn.Linear( in_size, 200); torch.nn.init.xavier_uniform_( self.fc1.weight );
		self.fc2 = torch.nn.Linear(200, 200); torch.nn.init.xavier_uniform_( self.fc2.weight );
		self.fc3 = torch.nn.Linear(200,   1); torch.nn.init.xavier_uniform_( self.fc3.weight );
		
	def forward(self, x):
		x = torch.nn.functional.relu( self.fc1(x) )
		x = torch.nn.functional.relu( self.fc2(x) )
		x = self.fc3(x)
		return x

class ConvolutionalNet(torch.nn.Module):
	def __init__(self, in_size ):
		super( ConvolutionalNet, self).__init__()
		self.conv1 = torch.nn.Conv1d(1,  32, 2); torch.nn.init.xavier_uniform_( self.conv1.weight );
		#self.conv2 = torch.nn.Conv1d(32, 32, 3); torch.nn.init.xavier_uniform_( self.conv1.weight );
		self.pool1 = torch.nn.AvgPool1d(2)
		#self.fc1   = torch.nn.Linear( 160, 150); torch.nn.init.xavier_uniform_( self.fc1.weight );
		self.fc1   = torch.nn.Linear( 96, 150); torch.nn.init.xavier_uniform_( self.fc1.weight );
		self.fc2   = torch.nn.Linear( 150, 150); torch.nn.init.xavier_uniform_( self.fc2.weight );
		self.fc3   = torch.nn.Linear( 150,   1); torch.nn.init.xavier_uniform_( self.fc3.weight );
	
	def forward(self, x):
		x = x.unsqueeze(1)
		x = torch.nn.functional.relu( self.pool1( self.conv1(x) ) )
		#x = torch.nn.functional.relu( self.conv2(x) )
		
		x = x.view( x.size()[0], -1 )
		
		x = torch.nn.functional.relu( self.fc1(x) )
		x = torch.nn.functional.relu( self.fc2(x) )
		x = self.fc3(x)
		return x

def limitDataUsingProcentiles( dataFrame ):
	if 'price' in dataFrame.columns :
		mask = True
		
		pricePerSquare       = ( dataFrame['price']/dataFrame['total_square'] )
		pricePerSquareValues = pricePerSquare.values
		
		robustScaler = RobustScaler(quantile_range=(15, 85) )
		robustScaler.fit( pricePerSquareValues.reshape((-1,1)) )
		pricePerSquareValues = robustScaler.transform( pricePerSquareValues.reshape((-1,1)) ).reshape(-1)
		
		mask = ( pricePerSquareValues > -1 ) & ( pricePerSquareValues  < 1 ) & mask
		
		dataFrame = dataFrame[ mask ]	
	
	return dataFrame
	
def loadCSVData( fileName, COLUMN_TYPE='NUMERICAL' ): # NUMERICAL, OBJECT, ALL

	dataFrame = pd.read_csv(
		fileName, 
		sep=";",
		encoding='cp1251', 
		#verbose=True, 
		keep_default_na=False
	).dropna(how="all")
	
	if 'price' in dataFrame.columns : dataFrame = dataFrame[ dataFrame['price'].apply( check_float ) ]
	dataFrame = dataFrame[ dataFrame.apply( check_row  , axis=1 ) ]
	
	for columnName in (FLOAT_COLUMNS + INT_COLUMNS):
		if columnName in dataFrame.columns : dataFrame[ columnName ] = dataFrame[ columnName ].astype( np.float32 )
	
	#print('Shape of the data with all features:', dataFrame.shape)
	if COLUMN_TYPE == 'NUMERICAL' :
		dataFrame = dataFrame.select_dtypes(exclude=['object'])
	#if COLUMN_TYPE == 'OBJECT'    :
	#	dataFrame = dataFrame.select_dtypes(exclude=['number'])
	#print('Shape of the data with numerical features:', dataFrame.shape)
	#print("List of features contained our dataset:",list( dataFrame.columns ))
	
	subset = None
	if 'price' in dataFrame.columns : 
		subset=['price', 'total_square', 'number_of_rooms' ]	
	else :
		subset=['total_square', 'number_of_rooms' ]	
	dataFrame.drop_duplicates(subset=subset, keep='first', inplace=True)	
	#Process floor number
	mask = True
	mask = mask & ( dataFrame['floor_number'] == 1                             ) 
	mask = mask | ( dataFrame['floor_number'] == dataFrame['number_of_floors'] )
	dataFrame['floor_flag'] = 1; dataFrame[ mask ]['floor_flag'] = 0;
	
	return dataFrame
