import torch
import numpy
import argparse
import bionetwork
import plotting
import pandas


inputAmplitude = 3
projectionAmplitude = 1.2

batchSize = 5
noiseLevel = 1e-3
MoAFactor = 1e-1
spectralFactor = 1e-3
maxIter = 8000
L2 = 1e-6
#weightAidFactor = 1e-8

#Get data number
parser = argparse.ArgumentParser(prog='Signaling simulation')
parser.add_argument('--leaveOut', action='store', default=None)
parser.add_argument('--scramble', action='store', default='false')
parser.add_argument('--activation', action='store', default='MML')
args = parser.parse_args()
curentId = int(args.leaveOut)
scramble = args.scramble == 'true'
activationType = str(args.activation)
nameModifyer =  activationType + '_'

testCondtions = pandas.read_csv('CVligandScreen/conditions.tsv', sep='\t', low_memory=False)
selectedTest = testCondtions.loc[curentId == testCondtions['Index'],:]['Condition'].values
print(curentId, selectedTest)

#Load network
networkList, nodeNames, modeOfAction = bionetwork.loadNetwork('data/ligandScreen-Model.tsv')
annotation = pandas.read_csv('data/ligandScreen-Annotation.tsv', sep='\t')
bionetParams = bionetwork.trainingParameters(iterations = 150, clipping=5, leak=0.01, spectralTarget=0.9)


inName = annotation.loc[annotation['ligand'],'code'].values
outName = annotation.loc[annotation['TF'],'code'].values
inName = numpy.intersect1d(nodeNames, inName)
outName = numpy.intersect1d(nodeNames, outName)

ligandInput = pandas.read_csv('data/ligandScreen-Ligands.tsv', sep='\t', low_memory=False, index_col=0)
TFOutput = pandas.read_csv('data/ligandScreen-TFs.tsv', sep='\t', low_memory=False, index_col=0)
ligandInput = ligandInput.loc[numpy.isin(ligandInput.index, selectedTest)==False, :]
TFOutput = TFOutput.loc[numpy.isin(TFOutput.index, selectedTest)==False, :]

#Subset input and output to intersecting nodes
inName = ligandInput.columns.values
outName = TFOutput.columns.values
inName = numpy.intersect1d(nodeNames, inName)
outName = numpy.intersect1d(nodeNames, outName)
ligandInput = ligandInput.loc[:,inName]
TFOutput = TFOutput.loc[:,outName]



model = bionetwork.model(networkList, nodeNames, modeOfAction, inputAmplitude, projectionAmplitude, inName, outName, bionetParams, activationType, torch.double)
model.inputLayer.weights.requires_grad = False
#model.network.balanceWeights()
model.network.preScaleWeights(0.7)

X = torch.tensor(ligandInput.values.copy(), dtype=torch.double)
Y = torch.tensor(TFOutput.values.copy(), dtype=torch.double)
N = X.shape[0]


if scramble:
    print('Scramble Y')
    trueY = Y.clone()
    while True:
        randomOrder = numpy.random.permutation(Y.shape[0])
        if numpy.all(randomOrder != numpy.array(range(len(randomOrder)))): #check that not correctly asigned by chance
            break
    Y = Y[randomOrder,:]
    nameModifyer += 'sramble_'
    


#%%
#Setup optimizer
criterion = torch.nn.MSELoss(reduction='mean')
#optimizer = torch.optim.Adam(model.parameters(), lr=1, weight_decay=0)
optimizer = torch.optim.Adam(model.parameters(), lr=1, weight_decay=0)
resetState = optimizer.state.copy()

mLoss =  criterion(torch.mean(Y, dim=0)*torch.ones(Y.shape), Y)
print(mLoss)

trainloader = torch.utils.data.DataLoader(range(N), batch_size=batchSize, shuffle=True)

stats = plotting.initProgressObject(maxIter)


#Evaluate network

stats = plotting.initProgressObject(maxIter)
curState = 0.5 * torch.ones((N, model.network.bias.shape[0]), dtype=torch.double, requires_grad=False)

e=0
for e in range(e, maxIter):
    curLr = bionetwork.oneCycle(e, maxIter, maxHeight = 1e-3, startHeight=1e-4, endHeight=1e-5, peak = 1000)
    optimizer.param_groups[0]['lr'] = curLr

    curLoss = []
    curEig = []
    model.train()
    for dataIndex in trainloader:
        optimizer.zero_grad()
        dataIn = X[dataIndex, :].view(len(dataIndex), X.shape[1])
        dataOut = Y[dataIndex, :].view(len(dataIndex), Y.shape[1])
        
        #model.network.weights.data = model.network.weights.data + 1e-8 * torch.randn(model.network.weights.shape)

        Yin = model.inputLayer(dataIn)
        Yin = Yin + noiseLevel * torch.randn(Yin.shape) # + dataError # /1e-3 * noiseLevel 
        YhatFull = model.network(Yin)
        Yhat = model.projectionLayer(YhatFull)
        #Yhat, YhatFull = model(dataIn)

        curState[dataIndex,:] = YhatFull.detach()
        
        fitLoss = criterion(Yhat, dataOut)

        signConstraint = MoAFactor * torch.sum(torch.abs(model.network.weights[model.network.getViolations(model.network.weights)]))

        stateLoss = 1e-5 * bionetwork.uniformLoss(curState, dataIndex, YhatFull, maxConstraintFactor = 1, targetMax = 1/projectionAmplitude)
        #stateLoss = curLr/1e-3 * 1e-5 * bionetwork.uniformLoss(curState, dataIndex, YhatFull, maxConstraintFactor = 1)
        #stateLoss = 1e-5 * uniformLoss(YhatFull)

        biasLoss = L2 * torch.sum(torch.square(model.network.bias))
        #absFilter = torch.abs(model.network.weights.detach())>0.001
        #weightLoss = L2 * torch.sum(torch.square(model.network.weights[absFilter]))
        weightLoss = L2 * torch.sum(torch.square(model.network.weights))

        spectralRadiusLoss, spectralRadius = bionetwork.spectralLoss(model.network, YhatFull.detach(), model.network.weights, expFactor = 10)
        spectralRadiusLoss = spectralFactor * spectralRadiusLoss


        projectionLoss = 1e-4 * torch.sum(torch.square(model.projectionLayer.weights - projectionAmplitude))

        ligandConstraint = 1e-4 * torch.sum(torch.square(model.network.bias[model.inputLayer.nodeOrder,:]))

        loss = fitLoss + signConstraint + spectralRadiusLoss + projectionLoss + weightLoss + ligandConstraint + stateLoss + biasLoss 

        loss.backward()

        #torch.nn.utils.clip_grad_norm_(model.network.bias.grad, 10, 2)
        #torch.nn.utils.clip_grad_norm_(model.network.weights.grad, 10, 2)

        optimizer.step()


        curLoss.append(fitLoss.item())
        curEig.append(spectralRadius.item())

    stats['loss'][e] = numpy.mean(numpy.array(curLoss))
    stats['lossSTD'][e] = numpy.std(numpy.array(curLoss))
    stats['eig'][e] = numpy.mean(numpy.array(curEig))
    stats['eigSTD'][e] = numpy.std(numpy.array(curEig))
    stats['rate'][e] = optimizer.param_groups[0]['lr']
    stats['violations'][e] = torch.sum(model.network.getViolations(model.network.weights)).item()

    if numpy.logical_and(e % 200 == 0, e>0):
        optimizer.state = resetState.copy()

    if e % 50 == 0:
        plotting.printStats(e, stats)

plotting.finishProgress(stats)

Yhat, YhatFull = model(X)
fileName = 'CVligandScreen/' + nameModifyer + 'model_' + str(curentId) + '.pt'
torch.save(model, fileName)
print('Saving', fileName)


