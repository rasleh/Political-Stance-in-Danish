import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as f
import torch.optim as optim
import collections
import sklearn.metrics as sk
import os

filePath = os.path.dirname(__file__)
avgFullDataPath = os.path.join(filePath, '../resources/avgQuote2Vec/fullDataset/')
avgPolSubsetPath = os.path.join(filePath, '../resources/avgQuote2Vec/nationalPolicy/')
fullDataPath = os.path.join(filePath, '../resources/quote2vec/fullDataset/')
polSubsetPath = os.path.join(filePath, '../resources/quote2vec/nationalPolicy/')

embSize = 300  # 300 sentence embeddings, 63 politician embeddings and 9 party embeddings
noClasses = 3
LSTMLayersVar = [1]
LSTMDimsVar = [100]  # 50 & 200 removed
ReLuLayersVar = [1]  # 2 removed
ReLuDimsVar = [50]  # 100, 200 removed
epochsVar = [1, 30, 50, 70, 100, 200, 300]
L2Var = [0.0, 0.0001, 0.0003]
dropoutVar = [0.0, 0.2, 0.5, 0.7, 1.0]


# Inspired by https://discuss.pytorch.org/t/example-of-many-to-one-lstm/1728/4 and
# https://pytorch.org/tutorials/beginner/nlp/sequence_models_tutorial.html
class LSTM(nn.Module):
    def __init__(self, LSTMLayers, LSTMDims, ReLULayers, ReLUDims):
        super(LSTM, self).__init__()
        self.LSTMLayers = LSTMLayers
        self.LSTMDims = LSTMDims
        self.ReLuLayers = ReLULayers
        self.ReLuDims = ReLUDims
        self.lstm = nn.LSTM(embSize, LSTMDims, LSTMLayers)
        # Initialize initial hidden state of the LSTM, all values being zero
        self.hiddenLayers = self.initializeHiddenLayers()
        print(len(self.hiddenLayers), '\n', self.hiddenLayers)

        # Initialize linear layers mapping to RelU Layers, and initialize ReLu layers
        denseLayers = collections.OrderedDict()
        denseLayers["linear0"] = torch.nn.Linear(LSTMDims, ReLUDims)
        denseLayers["ReLU0"] = torch.nn.ReLU()
        for i in range(ReLULayers-1):
            denseLayers['linear{}'.format(i+1)] = nn.Linear(ReLUDims, ReLUDims)
            denseLayers['ReLU{}'.format(i+1)] = nn.ReLU()
        # Initialize dropout layer
        denseLayers['dropOut'] = nn.Dropout(p=0.5)
        # Final layer mapping from last ReLU layer to labels
        denseLayers['linear{}'.format(ReLULayers)] = nn.Linear(ReLUDims, noClasses)
        self.hiddenLayers2Labels = nn.Sequential(denseLayers)

    def forward(self, quote):
        print(quote.size())
        for word in quote:
            lstmOut, self.hiddenLayers = self.lstm(word.view(len(word), 1, -1), self.hiddenLayers)
        labelSpace = self.hiddenLayers2Labels(lstmOut.view(len(word), -1))
        score = f.log_softmax(labelSpace, dim=1)
        return score

    def initializeHiddenLayers(self):
        return torch.zeros(self.LSTMLayers, 1,  self.LSTMDims), torch.zeros(self.LSTMLayers, 1, self.LSTMDims)


def loadVectors(path):
    with open(path, 'r', encoding='utf-8') as inFile:
        data = []
        for tempFeatureMatrix in inFile.readlines():
            features = tempFeatureMatrix.split(']\', \'[')
            featureMatrix = []
            for feature in features:
                feature = feature.replace('[', '').replace(']', '').replace('\'', '').replace('\n', '').split(', ')
                feature = [float(i) for i in feature]
                featureMatrix.append(feature)
            data.append((featureMatrix[:-1], int(featureMatrix[-1][0])))
        return data


def train(data, model, lossFunction, optimizer, epochs):
    epochLoss = 0.0
    for epoch in range(epochs):
        for quote, label in data:
            # Clear out gradients and hidden layers
            model.zero_grad()
            model.hiddenLayers = model.initializeHiddenLayers()
            target = torch.tensor([label])
            features = []
            for feature in quote:
                features.append([feature])
            labelScores = model(torch.tensor(features))
            loss = lossFunction(labelScores, target)
            loss.backward()
            optimizer.step()
            epochLoss += loss.item()
        print('Epoch %d, loss: %.5f' % (epoch + 1, epochLoss / 1000))
        epochLoss = 0


def test(data, model):
    predictedLabels = []
    actualLabels = []
    with torch.no_grad():
        for quote, label in data:
            features = []
            for feature in quote:
                # labelScores = model(torch.tensor([feature]))
                features.append([feature])
            labelScores = model(torch.tensor(features))
            predicted = torch.argmax(labelScores.data, dim=1)
            predictedLabels.extend(predicted.numpy())
            actualLabels.append(label)

    # Generate confusion matrix
    cMatrix = sk.confusion_matrix(actualLabels, predictedLabels, labels=[0, 1, 2])
    print("Confusion matrix:")
    print(cMatrix)
    cm = cMatrix.astype('float') / cMatrix.sum(axis=1)[:, np.newaxis]
    classAcc = cm.diagonal()
    acc = sk.accuracy_score(actualLabels, predictedLabels)
    f1 = sk.f1_score(actualLabels, predictedLabels, average='macro')
    print("Class acc:", classAcc)
    print("Accuracy: %.5f" % acc)
    print("F1-macro:", f1)
    return classAcc, acc, f1


def runFullBenchmark():
    with open(os.path.join(filePath, '../out/LSTM_benchmarkNoAvg.csv'), 'w') as outFile:
        outFile.write("epochs,LSTMLayers,LSTMDims,ReLULayers,ReLUDims,L2,totalAcc,f1,For,Against,Neutral\n")
        for LSTMLayer in LSTMLayersVar:
            for LSTMDim in LSTMDimsVar:
                for ReLULayer in ReLuLayersVar:
                    for ReLUDim in ReLuDimsVar:
                        for L2 in L2Var:
                            runSpecificBenchmark(fullDataPath, LSTMLayer, LSTMDim, ReLULayer, ReLUDim, L2, True, outFile)


def runSpecificBenchmark(path, LSTMLayers, LSTMDims, ReLULayers, ReLUDims, L2, fullRun, outFile):
    lossFunction = nn.NLLLoss()
    trainingData = loadVectors(path + 'trainData.txt')
    testData = loadVectors(path + 'testData.txt')
    model = LSTM(LSTMLayers, LSTMDims, ReLULayers, ReLUDims)
    optimizer = optim.SGD(model.parameters(), lr=0.001, weight_decay=L2)
    if not fullRun:
        outFile.write("epochs,LSTMLayers,LSTMDims,ReLULayers,ReLUDims,L2,totalAcc,f1,For,Against,Neutral\n")
    for i in range(len(epochsVar)):
        if i == 0:
            train(trainingData, model, lossFunction, optimizer, epochsVar[i])
            classAcc, totalAcc, f1 = test(testData, model)
            outFile.write(
               "%d,%d,%d,%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n" %
               (epochsVar[i], LSTMLayers, LSTMDims, ReLULayers, ReLUDims, L2, totalAcc, f1, classAcc[0],
                classAcc[1], classAcc[2]))
            outFile.flush()
        else:
            train(trainingData, model, lossFunction, optimizer, epochsVar[i]-epochsVar[i-1])
            classAcc, totalAcc, f1 = test(testData, model)
            outFile.write(
                "%d,%d,%d,%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n" %
                (epochsVar[i], LSTMLayers, LSTMDims, ReLULayers, ReLUDims, L2, totalAcc, f1, classAcc[0],
                 classAcc[1], classAcc[2]))
            outFile.flush()


runFullBenchmark()
# runSpecificBenchmark(fullDataPath, LSTMLayersVar[0], LSTMDimsVar[0], ReLuLayersVar[0], ReLuDimsVar[0], L2Var[1], False)
# LSTMBenchmark(os.path.join(filePath, '../out/LSTM_benchmarkNoAvg.csv'), avgQuote2Vec=False)
# run(fullDataPath, LSTMLayersVar[0], LSTMDimsVar[0], ReLuLayersVar[0], ReLuDimsVar[0], 3, L2Var[0], epochsVar[0], avgQuote2Vec=False)
