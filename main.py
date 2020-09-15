import sublime
import sublime_plugin
import os
import re
from .esprima import esprima
from datetime import datetime
import json

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

importErrors = {}
def show_import_error(view, filePath, location, text):
	region = sublime.Region(location[0], location[1])
	importErrors[filePath] = (region, text)
	draw_errors(view)

def draw_errors(view):
	regions = []
	for (region, text) in importErrors.values():
		regions.append(region)

	if len(importErrors.keys()) == 0:
		view.erase_regions("module_import_error")

	else:
		styling = sublime.DRAW_SOLID_UNDERLINE|sublime.DRAW_NO_FILL|sublime.DRAW_NO_OUTLINE
		view.add_regions("module_import_error", regions, "invalid.illegal", "", styling)

parseFileCache = {}
def parseFile(view, filePath, location):
	if filePath[0] != '.' or filePath[-3:] != '.js':
		show_import_error(view, filePath, location, "Import most be relative path to .js file")
		return {}

	fileDir = os.path.dirname(view.file_name())
	path = os.path.abspath(os.path.join(fileDir, filePath))

	if filePath in parseFileCache and os.path.getmtime(path) == parseFileCache[filePath][0]:
		return parseFileCache[filePath][1]

	try:
		with open(path, encoding='utf8') as file:
			content = file.read()
			try:
				ast = esprima.parseModule(content)
			except Exception as e:
				show_import_error(view, filePath, location, "Failed parsing module")
				return {}

			moduleName = os.path.basename(path)
			moduleCompletions = getModuleCompletionsFromAst(ast, moduleName)
			parseFileCache[filePath] = (os.path.getmtime(path), moduleCompletions)

			if filePath in importErrors:
				del importErrors[filePath]

			draw_errors(view)
			return moduleCompletions

	except FileNotFoundError:
		show_import_error(view, filePath, location, "Module not found")
		return {}

def findImports(view):
	regex = "import\s+\*\s+as\s+(\w+)\s+from\s+['\"](.+?)['\"];?"
	importLookahead = 1000

	viewHead = view.substr(sublime.Region(0, importLookahead))
	imports = {}
	for m in re.finditer(regex, viewHead):
		name = m.group(1)
		filePath = m.group(2)
		location = m.span(2)
		imports[name] = ('file', filePath, location)

	# remove errors that are not in import anymore
	importPaths = map(lambda x: x[1], imports.values())
	for path in list(importErrors):
		if path not in importPaths:
			del importErrors[path]

	localCompletions = findLocalCompletions()
	for name in localCompletions.keys():
		imports[name] = ('browser', localCompletions[name])

	return imports

localCompletionsCache = None
def findLocalCompletions():
	global localCompletionsCache
	
	if localCompletionsCache:
		return localCompletionsCache

	fileContent = sublime.load_resource("Packages/Resolve Javascript Modules/browser_completions.json")
	localCompletionsCache = json.loads(fileContent)
	return localCompletionsCache

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


def completeModuleExports(view, imports, moduleName, exportName):
	completions = []

	if moduleName not in imports:
		for key in imports:
			if key.startswith(moduleName):
				completions.append([key + '\tmodule', key])

		return completions

	if imports[moduleName][0] == 'file':
		moduleCompletions = parseFile(view, imports[moduleName][1], imports[moduleName][2])	

	else:
		moduleCompletions = imports[moduleName][1]

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
			completions += completeModuleExports(view, imports, moduleName, exportName)
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

		return getCompletions(view, locations)

	def on_activated(self, view):
		settings = view.settings().get('auto_complete_triggers')
		settings[0]['characters'] = './'
		view.settings().set('auto_complete_triggers', settings)

	def on_hover(self, view, point, hover_zone):
		for (region, text) in importErrors.values():
			if region.contains(point):
				view.show_popup(text, sublime.HIDE_ON_MOUSE_MOVE_AWAY, point)