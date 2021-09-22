import torch
import numpy
import matplotlib.pyplot as plt
import bionetwork
import pandas
from sklearn.decomposition import PCA
from sklearn.linear_model import LinearRegression
#from sklearn.manifold import TSNE
import umap
from scipy.stats import pearsonr
from sklearn.model_selection import KFold
import seaborn as sns

#Load network
networkList, nodeNames, modeOfAction = bionetwork.loadNetwork('data/KEGGnet-Model.tsv')
annotation = pandas.read_csv('data/KEGGnet-Annotation.tsv', sep='\t')
uniprot2gene = dict(zip(annotation['code'], annotation['name']))


inputAmplitude = 3
projectionAmplitude = 1.2


inName = annotation.loc[annotation['ligand'],'code'].values
outName = annotation.loc[annotation['TF'],'code'].values
inName = numpy.intersect1d(nodeNames, inName)
outName = numpy.intersect1d(nodeNames, outName)
inNameGenes = [uniprot2gene[x] for x in inName]
outNameGenes = [uniprot2gene[x] for x in outName]
nodeNameGene = [uniprot2gene[x] for x in nodeNames]

bionetParams = bionetwork.trainingParameters(iterations = 150, clipping=1, leak=0.01)
model = bionetwork.model(networkList, nodeNames, modeOfAction, inputAmplitude, projectionAmplitude, inName, outName, bionetParams, torch.double)
model = bionetwork.loadParam('synthNetModel/equationParams.txt', model, nodeNames)


#%%
N=100
simultaniousInput = 5
data = torch.zeros(N, len(inName), dtype=torch.double)

for i in range(N):
    data[i, numpy.random.randint(0, len(inName), simultaniousInput)] = torch.rand(simultaniousInput, dtype=torch.double)

conditions = bionetwork.generateConditionNames(data, inNameGenes)

Yhat, YhatFull = model(data)
df = pandas.DataFrame(Yhat.T.detach().numpy(), index=outNameGenes, columns=conditions)
sns.clustermap(df, cmap='RdBu_r', vmin=0, vmax=1) #, yticklabels=True

#%%

useUMap = False
correlationBasedDistance = True


N=2000
simultaniousInput = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
totalSamples = N * len(simultaniousInput)
data = torch.zeros(totalSamples, len(inName), dtype=torch.double)
sampleLabel = numpy.zeros(totalSamples)

k = 0
for i in range(len(simultaniousInput)):
    curSamples = simultaniousInput[i]
    for j in range(N):
        data[k, numpy.random.randint(0, len(inName), curSamples)] = torch.rand(curSamples, dtype=torch.double)
        sampleLabel[k] = i
        k+=1

#names = bionetwork.generateConditionNames(data, [uniprot2gene[x] for x in inName])

model.eval()
Ypredict, YpredictFull = model(data)
Ypredict = Ypredict.detach().numpy()

if useUMap:
    projection = PCA(n_components=8)
    principalComponents = projection.fit_transform(Ypredict)
    projection = umap.UMAP(n_neighbors=20)
    principalComponents = projection.fit_transform(principalComponents)
else:
    projection = PCA(n_components=8)
    principalComponents = projection.fit_transform(Ypredict)

print(projection.explained_variance_ratio_)
print(sum(numpy.array(projection.explained_variance_ratio_)))

#%%
def PCAString(i, projection):
    return 'PC {0:d} ({1:0.2f}%)'.format(i, 100*projection.explained_variance_ratio_[i-1])

selectedInputs = [5, 2, 1]
plt.rcParams["figure.figsize"] = (6,6)
minAndMax = [numpy.floor(numpy.min(principalComponents)), numpy.ceil(numpy.max(principalComponents))]

colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
colors.insert(2, '#000000')
plt.figure()

for i in range(4):
    plt.subplot(2, 2, i + 1)
    for j in range(len(selectedInputs)):
        curData = numpy.argwhere(numpy.isin(simultaniousInput, selectedInputs[j]))[0]
        plt.plot(principalComponents[sampleLabel==curData, i], principalComponents[sampleLabel==curData, i+1], 'o', color=colors[j])
        plt.xlim(minAndMax)
        plt.ylim(minAndMax)
        plt.xlabel(PCAString(i+1, projection))
        plt.ylabel(PCAString(i+2, projection))
    if i==0:
        plt.legend(selectedInputs)

plt.tight_layout()


plt.rcParams["figure.figsize"] = (3,3)
plt.figure()
i=0
minAndMax = [numpy.floor(numpy.min(principalComponents[:,0:2])), numpy.ceil(numpy.max(principalComponents[:,0:2]))]

for j in range(len(selectedInputs)):
    curData = numpy.argwhere(numpy.isin(simultaniousInput, selectedInputs[j]))[0]
    plt.plot(principalComponents[sampleLabel==curData, i], principalComponents[sampleLabel==curData, i+1], 'o', color=colors[j])
    plt.xlim(minAndMax)
    plt.ylim(minAndMax)
    plt.xlabel(PCAString(i+1, projection))
    plt.ylabel(PCAString(i+2, projection))
plt.legend(selectedInputs, frameon=False)


#%%
plt.figure()
plt.rcParams["figure.figsize"] = (3,3)
model = LinearRegression()
kf = KFold(n_splits=20)

results = numpy.zeros((len(simultaniousInput), 3))
allX = data.numpy()
allY = Ypredict

X = allX[sampleLabel==0,:]
Y = allY[sampleLabel==0,:]
referenceModel = model.fit(X, Y)
for i in range(len(simultaniousInput)):
    X = allX[sampleLabel==i,:]
    Y = allY[sampleLabel==i,:]
    Yhat = referenceModel.predict(X)
    r, p = pearsonr(Y.flatten(), Yhat.flatten())
    results[i, 0] = r

for i in range(len(simultaniousInput)):
    X = allX[sampleLabel==i,:]
    Y = allY[sampleLabel==i,:]
    bestModel = model.fit(X, Y)
    Yhat =  bestModel.predict(X)
    r, p = pearsonr(Y.flatten(), Yhat.flatten())
    results[i, 1] = r

for i in range(len(simultaniousInput)):
    X = allX[sampleLabel==i,:]
    Y = allY[sampleLabel==i,:]
    Yhat = numpy.zeros(Y.shape)
    for train_index, test_index in kf.split(X):
        bestModel = model.fit(X[train_index,:], Y[train_index,:])
        Yhat[test_index,:] = bestModel.predict(X[test_index,:])
    r, p = pearsonr(Y.flatten(), Yhat.flatten())
    results[i, 2] = r


plt.plot(simultaniousInput, results[:,0])
#plt.plot(simultaniousInput, results[:,1])
plt.plot(simultaniousInput, results[:,2])

#plt.plot(simultaniousInput, results[:,2])
plt.ylim([0, 1])
plt.xlim([1, 10])
plt.xticks(numpy.arange(1, 11))
plt.xlabel('Simultanious Input')
plt.ylabel('Correlation')
plt.legend(['Extrapolation', 'Best fit'], frameon=False)  #'Best fit',
