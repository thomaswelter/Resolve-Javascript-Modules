import sublime
import sublime_plugin
import os
import re
from resolve_js_modules.esprima import esprima
from datetime import datetime
import json

pluginDir = os.path.dirname(os.path.realpath(__file__))

def log(text):
	logPath = os.path.join(pluginDir, "log.txt")

	with open(logPath, 'a', encoding='utf8') as logFile:
		logFile.write('\n{} > {}'.format(str(datetime.now()), text))

def formatFunction(moduleName, name, params):
	args = []
	if params:
		for param in params:
			if param.type == 'Identifier':
				args.append(param.name)

			if param.type == 'AssignmentPattern' and param.left.type == 'Identifier':
				args.append(param.left.name)

	suggestion = '{}({})\t{}'.format(name, ', '.join(args), moduleName)

	encapped = ['${{{}:{}}}'.format(i+1, name) for i,name in enumerate(args)]
	argString = ', '.join(encapped)
	completed = '{}({})'.format(name, argString)

	return [suggestion, completed]

def getModuleCompletionsFromAst(ast, moduleName):	
	completions = {}
	rootVars = {}

	for node in ast.body:
		if node.type == 'ExportNamedDeclaration':
			if node.declaration and node.declaration.type == 'FunctionDeclaration':
				name = node.declaration.id.name
				completions[name] = formatFunction(moduleName, name, node.declaration.params)

			if node.declaration and node.declaration.type == 'VariableDeclaration':
				for declarator in node.declaration.declarations:
					if declarator.type == 'VariableDeclarator':
						name = declarator.id.name

						if declarator.init and declarator.init.type == 'ArrowFunctionExpression':
							completions[name] = formatFunction(moduleName, name, declarator.init.params)

						elif declarator.init and declarator.init.type == 'FunctionExpression':
							completions[name] = formatFunction(moduleName, name, declarator.init.params)

						else:
							completions[name] = [name + '\t{}'.format(moduleName), name]

			for specifier in node.specifiers:
				if specifier.type == 'ExportSpecifier':
					exported = specifier.exported.name
					local = specifier.local.name

					if local in rootVars:
						completions[exported] = rootVars[local](exported)

		if node.type == 'VariableDeclaration':
			for declarator in node.declarations:
				if declarator.type == 'VariableDeclarator':
					name = declarator.id.name

					if declarator.init and declarator.init.type == 'ArrowFunctionExpression':
						rootVars[name] = (lambda p: lambda n: formatFunction(moduleName, n, p))(declarator.init.params)

					elif declarator.init and declarator.init.type == 'FunctionExpression':
						rootVars[name] = (lambda p: lambda n: formatFunction(moduleName, n, p))(declarator.init.params)

					else:
						rootVars[name] = lambda n: [n + '\t{}'.format(moduleName), n]

	return completions

parseFileCache = {}
def parseFile(filePath):
	if filePath in parseFileCache and os.path.getmtime(filePath) == parseFileCache[filePath][0]:
		return parseFileCache[filePath][1]

	moduleName = os.path.basename(filePath)

	try:
		with open(filePath, encoding='utf8') as file:
			ast = esprima.parseModule(file.read())
			moduleCompletions = getModuleCompletionsFromAst(ast, moduleName)
			parseFileCache[filePath] = (os.path.getmtime(filePath), moduleCompletions)
			return moduleCompletions

	except FileNotFoundError:
		log('File not found: ' + filePath)
		return {}

def findImports(view):
	regex = "import\s+\*\s+as\s+(\w+)\s+from\s+['\"](\.\.?/.+\.js)['\"];?"
	importLookahead = 1000

	viewHead = view.substr(sublime.Region(0, importLookahead))
	fileDir = os.path.dirname(view.file_name())
	imports = {}
	for (name, filePath) in re.findall(regex, viewHead):
		imports[name] = os.path.abspath(os.path.join(fileDir, filePath))

	localCompletions = findLocalCompletions()
	for name in localCompletions.keys():
		imports[name] = localCompletions[name]

	return imports

localCompletionsCache = None
def findLocalCompletions():
	global localCompletionsCache
	
	if localCompletionsCache:
		return localCompletionsCache

	completionsPath = os.path.join(pluginDir, "browser_completions.json")
	with open(completionsPath, encoding='utf8') as file:
		completions = json.loads(file.read())

	localCompletionsCache = completions
	return completions

def completeModuleFilePath(view, path):
	fileDir = os.path.dirname(view.file_name())
	joined = os.path.abspath(os.path.join(fileDir, path))
	try:
		files = os.listdir(joined)

	except:
		return []

	completions = []
	for name in files:
		if name.find('.') == -1:
			completions.append([name + '\tdir', name])

		if name[-3:] == '.js':
			completions.append([name + '\tfile', name])

	return completions


def completeModuleExports(imports, moduleName, exportName):
	completions = []

	if moduleName not in imports:
		for key in imports:
			if key.startswith(moduleName):
				completions.append([key + '\tmodule', key])

		return completions

	if isinstance(imports[moduleName], str):
		moduleCompletions = parseFile(imports[moduleName])	

	else:
		moduleCompletions = imports[moduleName]

	for key in moduleCompletions.keys():
		if key.startswith(exportName):
			completions.append(moduleCompletions[key])

	return completions

def getCompletions(view, locations):
	imports = findImports(view)

	hideOtherCompletions = False
	completions = []

	for point in locations:
		region = view.line(point)
		line = view.substr(region)

		m = re.search('(\w+)\.?(\w*)$', line)
		if m and m.group() != '':
			moduleName = m.group(1)
			exportName = m.group(2)
			completions += completeModuleExports(imports, moduleName, exportName)
			continue

		m = re.search("^import.+?['\"]([^'\"]*)['\"]?;?$", line)
		if m:
			completions += completeModuleFilePath(view, m.group(1))
			hideOtherCompletions = True
			continue

	if hideOtherCompletions:
		return (completions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

	return completions

class resolve_js_modules(sublime_plugin.EventListener):
	def on_query_completions(self, view, prefix, locations):
		if 'source.js' not in view.scope_name(0):
			return

		try:
			return getCompletions(view, locations)

		except Exception as e:
			log(e)

		return None

	def on_activated(self, view):
		settings = view.settings().get('auto_complete_triggers')
		settings[0]['characters'] = './'
		view.settings().set('auto_complete_triggers', settings)