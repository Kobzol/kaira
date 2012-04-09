#
#    Copyright (C) 2011 Stanislav Bohm
#
#    This file is part of Kaira.
#
#    Kaira is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3 of the License, or
#    (at your option) any later version.
#
#    Kaira is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Kaira.  If not, see <http://www.gnu.org/licenses/>.
#

import base.utils as utils
from base.neltypes import t_int, t_string, t_float, t_double, t_bool
from base.writer import Writer
from base.expressions import ExprVar
import emitter
import os.path

from base.gentools import get_ordered_types, get_edges_mathing

def emit_declarations(emitter, decls, reference = False):
    if reference:
        r = "&"
    else:
        r = ""
    return ",".join(("{0} {2}{1}".format(emitter.emit_type(t), name, r) for name, t in decls))

class CppWriter(Writer):

    def block_begin(self):
        self.line("{{")
        self.indent_push()

    def block_end(self):
        self.indent_pop()
        self.line("}}")

    def if_begin(self, expr):
        self.line("if ({0}) {{", expr)
        self.indent_push()

    def while_begin(self, expr):
        self.line("while ({0}) {{", expr)
        self.indent_push()

    def do_begin(self):
        self.line("do {{")
        self.indent_push()

    def do_end(self, expr):
        self.indent_pop()
        self.line("}} while ({0});", expr)

    def write_class_head(self, name, parent = None):
        if parent:
            inheritance = " : public {0} ".format(parent)
        else:
            inheritance = ""
        self.line("class {0} {1}{{", name, inheritance)
        self.indent_push()
        self.line("public:")

    def write_class_end(self):
        self.indent_pop()
        self.line("}};")

    def write_var_decl(self, name, t, reference = False):
        self.line("{0} {2}{1};", t, name, "&" if reference else "")

    def write_method_start(self, decl):
        self.line(decl + " {{")
        self.indent_push()

    def write_method_end(self):
        self.indent_pop()
        self.line("}}")

    def write_constructor(self, name, decls, inits):
        decl = "{0}({1})".format(name, decls)
        if inits:
            decl += " : " + ",".join(inits)
        self.write_method_start(decl)

    def line_directive(self, filename, lineno):
        self.line('#line {0} "{1}"', lineno, filename)


class Builder(CppWriter):

    def __init__(self, project, output_filename):
        CppWriter.__init__(self)
        self.emitter = emitter.Emitter(project)
        self.project = project
        self.output_filename = output_filename

    def write_header(self):
        self.line("/* This file is automatically generated")
        self.line("   do not edit this file directly! */")
        self.emptyline()
        self.line('#include <cailie.h>')
        self.line('#include <algorithm>')
        self.line('#include <stdlib.h>')
        self.line('#include <stdio.h>')
        self.line('#include <sstream>')
        self.line('#include "head.cpp"')
        self.emptyline()

    def write_parameters(self):
        for p in self.project.get_parameters():
            tstr = self.emitter.emit_type(p.get_type())
            self.line("{0} __param_{1};", tstr, p.get_name())
            decl = "{0} parameter_{1}()".format(tstr, p.get_name())
            code = "\treturn __param_{0};".format(p.get_name())
            self.write_function(decl, code)

    def write_main(self):
        self.line("int main(int argc, char **argv)")
        self.block_begin()
        self.line("ca_project_description({0});", self.emitter.const_string(self.project.description))
        params = self.project.get_parameters()
        names = ",".join((self.emitter.const_string(p.name) for p in params))
        self.line("const char *pnames[] = {{{0}}};", names)
        descriptions = ",".join((self.emitter.const_string(p.description) for p in params))
        self.line("const char *pdesc[] = {{{0}}};", descriptions)
        pvalues = ",".join(("&__param_" + p.name for p in params))
        self.line("int *pvalues[] = {{{0}}};", pvalues)
        self.line("ca_init(argc, argv, {0}, pnames, pvalues, pdesc);", len(params))
        for net in self.project.nets:
            self.register_net(net)
        defs = [ "def_" + str(net.id) for net in self.project.nets ]
        self.line("CaNetDef *defs[] = {{{0}}};", ",".join(defs))
        self.line("ca_setup({0}, defs);", len(defs));
        self.line("ca_spawn_toplevel_net(0);");
        self.line("ca_main();");
        self.line("return 0;")
        self.block_end()

    def register_net(self, net):
        self.line("CaNetDef *def_{0.id} = new CaNetDef({2}, {0.id}, {1}, spawn_{0.id}, {3}, {4});", net,
                     len(net.transitions), net.get_index(), self.emitter.const_boolean(net.is_local()),
                     self.emitter.const_boolean(net.autohalt))
        for i, tr in enumerate(net.transitions):
            self.line("def_{0.id}->register_transition({2}, {1.id},(CaEnableFn*) enable_{1.id},"
                      " enable_check_{1.id});", net, tr, i)

    def add_tuple_class(self, t):
        class_name = t.get_safe_name()
        self.write_class_head(class_name)
        decls = [ ("t{0}".format(i), ta) for i, ta in enumerate(t.args) ]
        for name, ta in decls:
            self.write_var_decl(name, self.emit_type(ta))

        self.write_constructor(class_name, self.emit_declarations(decls), [ "{0}({0})".format(name) for name, _ in decls ])
        self.write_method_end()

        args = [ "{0}({1})".format(e, self.get_unpack_code(t, "unpacker")) for e, t in decls ]
        self.write_constructor(class_name, "CaUnpacker &unpacker", args)
        self.write_method_end()

        self.write_constructor(class_name, "", [])
        self.write_method_end()

        self.write_method_start("std::string as_string()")
        self.line('return std::string("(") + {0} + ")";',
                  ' + "," +'.join((self.code_as_string(e, t) for e, t in decls)))
        self.write_method_end()

        self.write_method_start("size_t get_mem_size()")
        self.line('return {0};', ' + '.join((self.get_size_code(t, e) for e, t in decls)))
        self.write_method_end()

        self.write_method_start("void pack(CaPacker &packer)")
        for e, t in decls:
            self.line(self.get_pack_code(t, "packer", e) + ";")
        self.write_method_end()

        self.write_class_end()

    def write_array_as_string(self, t):
        self.line("std::string array_{0}_as_string(std::vector <{1} > &vector)",
                  t.get_safe_name(), self.emit_type(t))
        self.block_begin()
        self.line("std::stringstream osstream;")
        self.line('osstream << "[";')
        self.line("if (vector.size() > 0)")
        self.block_begin()
        self.line("std::vector<{0} >::iterator i = vector.begin();", self.emit_type(t))
        self.line("osstream << {0};", self.code_as_string("*i", t))
        self.line("i++;")
        self.line("for (; i != vector.end(); i++)")
        self.block_begin()
        self.line('osstream << "," << {0};', self.code_as_string("*i", t))
        self.block_end()
        self.block_end()
        self.line('osstream << "]";')
        self.line("return osstream.str();")
        self.block_end()

    def write_array_size(self, t):
        self.line("size_t array_{0}_size(std::vector <{1} > &vector)",
                  t.get_safe_name(), self.emit_type(t))
        self.block_begin()
        self.line("size_t s = sizeof(size_t);")
        # FIXME: Optimize for constant size objects
        self.line("for (std::vector<{0} >::iterator i = vector.begin(); i != vector.end(); i++)",
                  self.emit_type(t))
        self.block_begin()
        self.line("s += {0};", self.get_size_code(t, "(*i)"))
        self.block_end()
        self.line("return s;")
        self.block_end()

    def write_array_pack(self, t):
        self.line("void array_{0}_pack(CaPacker &packer, std::vector <{1} > &vector)",
                  t.get_safe_name(), self.emit_type(t))
        self.block_begin()
        self.line("packer.pack_size(vector.size());")
        self.line("for (std::vector<{0} >::iterator i = vector.begin(); i != vector.end(); i++)",
                  self.emit_type(t))
        self.block_begin()
        self.line("{0};", self.get_pack_code(t, "packer", "(*i)"))
        self.block_end()
        self.block_end()

    def write_array_unpack(self, t):
        self.line("std::vector <{1} > array_{0}_unpack(CaUnpacker &unpacker)",
                  t.get_safe_name(), self.emit_type(t))
        self.block_begin()
        self.line("size_t s = unpacker.unpack_size();")
        self.line("std::vector <{0} > vector(s);", self.emit_type(t))
        self.line("for (size_t t = 0; t < s; t++)")
        self.block_begin()
        self.line("vector[t] = {0};", self.get_unpack_code(t, "unpacker"))
        self.block_end()
        self.line("return vector;")
        self.block_end()

    def write_types(self):
        for t in get_ordered_types(self.project):
            if t.name == "":
                self.add_tuple_class(t)
            if len(t.args) == 1 and t.name == "Array":
                self.write_array_as_string(t.args[0])
                self.write_array_size(t.args[0])
                self.write_array_pack(t.args[0])
                self.write_array_unpack(t.args[0])

    def write_tokens_struct(self, tr):
        """
            Write class that holds tokens when transition spawn a module.
            This values are used when transition is finished.
        """

        class_name = "Tokens_{0.id}".format(tr)
        self.write_class_head(class_name)

        matches, _, _ = get_edges_mathing(self.project, tr)

        for i, (edge, _) in enumerate(matches):
            place_t = self.emit_type(edge.get_place_type())
            self.line("CaToken<{0} > *token_{1};", place_t, i)

        self.write_class_end()

    def write_vars_struct(self, tr):
        """
            Write class that servers as interface for transition's inner functions.
        """

        class_name = "Vars_{0.id}".format(tr)
        self.write_class_head(class_name)

        decls = tr.get_context().items()
        decls.sort(key=lambda x: x[0]) # Sort by variables names

        self.write_constructor(class_name, self.emit_declarations(decls, True),
                               ["{0}({0})".format(name) for name, _ in decls ])
        self.write_method_end()

        for name, t in decls:
            self.write_var_decl(name, self.emit_type(t), True)
        self.write_class_end()

    def write_transition_forward(self, tr):
        if tr.subnet is not None:
            self.write_tokens_struct(tr)
        elif tr.code is not None:
            self.write_vars_struct(tr)
        self.line("bool enable_check_{0.id}(CaThread *thread, CaNet *net);", tr)

    def write_transition_net_finalizer(self, tr):

        def variable_emitter(name):
            for edge in tr.subnet.get_interface_edges_in():
                if edge.is_normal() and edge.expr.name == name:
                    return "subnet->place_{0.id}.first_value()".format(edge.get_place())
                elif edge.is_packing() and edge.varname == name:
                    return "subnet->place_{0.id}.to_vector()".format(edge.get_place())
            return vars_access[name].emit(em)


        self.line("void transition_finalizer_{0.id}(CaThread *thread, "
                  "Net_{1.id} *n, Net_{2.id} *subnet, Tokens_{0.id} *tokens)", tr, tr.net, tr.subnet)
        self.block_begin()
        self.line("CaContext ctx(thread, n);")
        conditions = []
        for edge in tr.subnet.get_interface_edges_in():
            if edge.is_normal():
                if not isinstance(edge.expr, ExprVar):
                    raise utils.PtpException("Invalid expression", edge.expr.source)
                conditions.append("subnet->place_{0.id}.is_empty()".format(edge.get_place()))
        if conditions:
            self.if_begin("||".join(conditions))
            self.line('fprintf(stderr, "Token in output places of module {0} not found\\n");', tr.subnet.get_name())
            self.line("exit(-1);")
            self.block_end()

        self.line("bool lock = false;")

        matches, _, vars_access = get_edges_mathing(self.project, tr)

        em = emitter.Emitter(self.project)

        for i, (edge, _) in enumerate(matches):
            em.set_extern("token_{0}".format(i), "tokens->token_{0}->element".format(i))

        em.variable_emitter = variable_emitter
        for edge in tr.get_packing_edges_out() + tr.get_normal_edges_out():
            self.write_send_token(self, em, edge)

        if tr.net.has_autohalt():
            self.write_decrement_running_transitions(self, "n")
        self.line("if (lock) n->unlock();")

        for i in xrange(len(matches)):
            self.line("delete tokens->token_{0};", i)

        self.line("delete tokens;")
        self.block_end()

    def write_transition(self, tr):
        if tr.code is not None:
            self.write_transition_user_function(tr)
        if tr.subnet is not None:
            self.write_transition_net_finalizer(tr)
        self.write_enable(tr)
        self.write_enable_check(tr)

    def write_function(self, declaration, code, file_lineno = None):
        if file_lineno:
            filename, lineno = file_lineno
            self.line_directive(filename, lineno)
        self.raw_line(declaration)
        self.line("{{")
        self.raw_text(code)
        self.line("}}")
        if file_lineno:
            self.line_directive(os.path.basename(self.output_filename), self.get_next_line_number())

    def write_transition_user_function(self, tr):
        declaration = "void transition_user_fn_{0.id}(CaContext &ctx, Vars_{0.id} &var)".format(tr)
        self.write_function(declaration, tr.code, ("*{0.id}/function".format(tr), 1))

    def write_place_user_function(self, place):
        t = self.emit_type(place.type)
        declaration = "void place_user_fn_{0.id}(CaContext &ctx, std::vector<{1} > &tokens)".format(place, t)
        self.write_function(declaration, place.code, ("*{0.id}/init_function".format(place), 1))

    def write_user_function(self, ufunction):
        params =  ufunction.get_parameters()
        if ufunction.with_context:
            params = [ ("ctx", "CaContext &") ] + list(params)
        returntype = self.emit_type(ufunction.get_returntype())
        declaration = "{1} ufunction_{0}({2})".format(ufunction.get_name(),
                                                      returntype, self.emit_declarations(params))
        source = ("*{0.id}/user_function".format(ufunction), 1)
        self.write_function(declaration, ufunction.get_code(), source)

    def write_user_functions(self):
        for ufunction in self.project.get_user_functions():
            self.write_user_function(ufunction)

    def get_size_code(self, t, code):
        if t == t_int or t == t_float or t == t_double:
            return "sizeof({0})".format(code)
        if t == t_string:
            return "(sizeof(size_t) + ({0}).size())".format(code)
        if t.name == "":
            return "({0}).get_mem_size()".format(code)
        if t.name == "Array":
            return "array_{1}_size({0})".format(code, t.args[0].get_safe_name())
        etype = self.project.get_extern_type(t.name)
        if etype:
            if etype.get_transport_mode() == "Disabled":
                raise utils.PtpException("Transport of type '{0.name}' is disabled".format(etype))
            if etype.get_transport_mode() == "Direct":
                return "sizeof({0})".format(code)
            return "{0.name}_getsize({1})".format(etype, code)
        raise Exception("Unknown type: " + str(t))

    def get_pack_code(self, t, packer, code):
        if t == t_int:
            return "{0}.pack_int({1})".format(packer, code)
        if t == t_string:
            return "{0}.pack_string({1})".format(packer, code)
        if t == t_float:
            return "{0}.pack_float({1})".format(packer, code)
        if t == t_double:
            return "{0}.pack_double({1})".format(packer, code)
        if t.name == "Array":
            return "array_{2}_pack({0}, {1})".format(packer, code, t.args[0].get_safe_name())
        if t.name == "":
            return "({1}).pack({0})".format(packer, code)
        etype = self.project.get_extern_type(t.name)
        if etype:
            if etype.get_transport_mode() == "Disabled":
                raise utils.PtpException("Transport of type '{0.name}' is disabled".format(etype))
            if etype.get_transport_mode() == "Direct":
                return "{0}.pack(&{1}, sizeof({1}))".format(packer, code)
            return "{0.name}_pack({1}, {2})".format(etype, packer, code)
        raise Exception("Unknown type: " + str(t))

    def get_unpack_code(self, t, unpacker):
        if t == t_int:
            return "{0}.unpack_int()".format(unpacker)
        if t == t_string:
            return "{0}.unpack_string()".format(unpacker)
        if t == t_float:
            return "{0}.unpack_float()".format(unpacker)
        if t == t_double:
            return "{0}.unpack_double()".format(unpacker)
        if t.name == "Array":
            return "array_{1}_unpack({0})".format(unpacker, t.args[0].get_safe_name())
        if t.name == "":
            return "{0}({1})".format(t.get_safe_name(), unpacker)
        etype = self.project.get_extern_type(t.name)
        if etype:
            if etype.get_transport_mode() == "Disabled":
                raise utils.PtpException("Transport of type '{0.name}' is disabled".format(etype))
            if etype.get_transport_mode() == "Direct":
                return "* (({1} *) {0}.unpack(sizeof({1})))".format(unpacker, etype.get_rawtype())
            return "{0.name}_unpack({1})".format(etype, unpacker)
        raise Exception("Unknown type: " + str(t))

    def is_directly_packable(self, t):
        if t.name == "":
            return all((self.is_directly_packable(x) for x in t.args))
        return t == t_int

    def write_activation(self, w, net, transitions):
        for tr in transitions:
            w.line("{0}->activate_transition_by_pos_id({1});",net, tr.get_pos_id())

    def write_send_token(self, w, em, edge):

        def write_lock():
            w.if_begin("!lock")
            w.line("n->lock();")
            w.line("lock = true;")
            w.block_end()

        def write_unlock():
            w.if_begin("lock")
            w.line("n->unlock();")
            w.line("lock = false;")
            w.block_end()

        method = "add" if edge.is_normal() else "add_all"

        if edge.guard is not None:
            w.if_begin(edge.guard.emit(em))
        if edge.is_local():
            write_lock()
            w.line("n->place_{0.id}.{2}({1});", edge.get_place(), edge.expr.emit(em), method)
            self.write_activation(w, "n", edge.get_place().get_transitions_out())
        else:
            if edge.is_unicast():
                sendtype = ""
                w.line("int target_{0.id} = {1};", edge, edge.target.emit(em))
                w.if_begin("target_{0.id} == thread->get_process_id()".format(edge))
                write_lock()
                w.line("n->place_{0.id}.{2}({1});", edge.get_place(), edge.expr.emit(em), method)
                self.write_activation(w, "n", edge.get_place().get_transitions_out())
                w.indent_pop()
                w.line("}} else {{")
                w.indent_push()
            else:
                w.line("std::vector<int> target_{0.id} = {1};", edge, edge.target.emit(em))
                sendtype = "_multicast"
                w.block_begin()
            write_unlock();
            t = edge.get_place_type()
            traw = self.emit_type(t)
            w.line("{0} value = {1};", self.emit_type(edge.expr.nel_type), edge.expr.emit(em))
            if edge.is_normal(): # Pack normal edge
                w.line("CaPacker packer({0}, CA_RESERVED_PREFIX);", self.get_size_code(t, "value"))
                w.line("{0};", self.get_pack_code(t, "packer", "value"))
                w.line("thread->send{0}(target_{1.id}, n, {2}, packer);",
                       sendtype, edge, edge.get_place().get_pos_id())
            else: # Pack packing edge
                if self.is_directly_packable(t):
                    w.line("size_t size = sizeof({0}) * value.size();", self.emit_type(t))
                else:
                    w.line("size_t size = 0;")
                    w.line("for (std::vector<{0} >::iterator i = value.begin(); i != value.end(); i++)", traw)
                    w.block_begin()
                    w.line("size += {0};", self.get_size_code(t, "(*i)"))
                    w.block_end()
                # TODO: Pack in one step if type is directly packable
                w.line("CaPacker packer(size, CA_RESERVED_PREFIX);")
                w.line("for (std::vector<{0} >::iterator i = value.begin(); i != value.end(); i++)", traw)
                w.block_begin()
                w.line("{0};", self.get_pack_code(t, "packer", "(*i)"))
                w.block_end()
                w.line("thread->multisend{0}(target_{1.id}, n, {2}, value.size(), packer);",
                       sendtype,edge, edge.get_place().get_pos_id())
            w.block_end()
        if edge.guard is not None:
            w.block_end()

    def write_decrement_running_transitions(self, w, varname):
        w.if_begin("!lock")
        w.line("{0}->lock();", varname)
        w.line("lock = true;")
        w.block_end()
        w.line("{0}->dec_running_transitions();", varname)

    def write_enable(self, tr):
        self.line("int enable_{0.id}(CaThread *thread, CaNet *net)", tr)
        self.block_begin()
        self.line("CaContext ctx(thread, net);")

        w = CppWriter()
        matches, _, vars_access = get_edges_mathing(self.project, tr)

        em = emitter.Emitter(self.project)
        for i, (edge, _) in enumerate(matches):
            em.set_extern("token_{0}".format(i), "token_{0}->element".format(i))

        context = tr.get_context()
        names = context.keys()
        names.sort()

        token_out_counter = 0
        vars_code = {}

        for name in names:
            if name not in vars_access: # Variable is not obtained from output
                t = self.emit_type(context[name])
                w.line("{1} out_value_{0};", token_out_counter, t)
                #w.line("CaToken<{1}> token_out_{0}(value);", token_out_counter, t)
                vars_code[name] = "out_value_{0}".format(token_out_counter);
                token_out_counter += 1
            else:
                vars_code[name] = vars_access[name].emit(em)

        em.variable_emitter = lambda name: vars_code[name]

        for i, (edge, _) in enumerate(matches):
            w.line("n->place_{1.id}.remove(token_{0});", i, edge.get_place())

        w.line("net->activate_transition_by_pos_id({0});", tr.get_pos_id())
        if tr.net.has_autohalt():
            w.line("net->inc_running_transitions();")

        for edge in tr.get_packing_edges_in():
            w.line("{1} = n->place_{0.id}.to_vector_and_clear();", edge.get_place(), em.variable_emitter(edge.varname))

        if tr.subnet is not None:
            retvalue = "CA_TRANSITION_FIRED_WITH_MODULE"
            w.line("n->unlock();")
            w.line("bool lock = true;")
            w.line("Net_{0.id} *n = (Net_{0.id}*) thread->spawn_net({1}, net);", tr.subnet, tr.subnet.get_index())
            w.line("Tokens_{0.id} *tokens = new Tokens_{0.id}();", tr)
            for i in xrange(len(matches)):
                w.line("tokens->token_{0} = token_{0};", i)

            w.line("n->set_finalizer((CaNetFinalizerFn*) transition_finalizer_{0.id}, tokens);", tr)
            for edge in tr.subnet.get_interface_edges_out():
                self.write_send_token(w, em, edge)
        else: # Without subnet
            retvalue = "CA_TRANSITION_FIRED"
            if tr.code is not None:
                w.line("net->unlock();")
                if len(names) == 0:
                    w.line("Vars_{0.id} vars;", tr)
                else:
                    w.line("Vars_{0.id} vars({1});", tr, ",".join([ vars_code[n] for n in names ]))
                w.line("transition_user_fn_{0.id}(ctx, vars);", tr)
                w.line("bool lock = false;")
            else:
                w.line("bool lock = true;")

            for edge in tr.get_packing_edges_out() + tr.get_normal_edges_out():
                self.write_send_token(w, em, edge)
            if tr.net.has_autohalt():
                self.write_decrement_running_transitions(w, "net")

        w.line("if (lock) n->unlock();")

        if tr.subnet is None:
            for i, (edge, _) in enumerate(matches):
                w.line("delete token_{0};", i, edge.get_place())

        if tr.net.is_module():
            w.line("if (ctx.get_halt_flag()) thread->halt(net);")
        w.line("return {0};", retvalue)

        self.write_enable_pattern_match(tr, w)
        self.line("return CA_NOT_ENABLED;")
        self.block_end()

    def write_enable_check(self, tr):
        self.line("bool enable_check_{0.id}(CaThread *thread, CaNet *net) {{", tr)
        self.indent_push()

        w = CppWriter()
        w.line("return true;")
        self.write_enable_pattern_match(tr, w)
        self.line("return false;")
        self.block_end()

    def write_enable_pattern_match(self, tr, fire_code):
        matches, initcode, vars_access = get_edges_mathing(self.project, tr)

        em = emitter.Emitter(self.project)
        em.variable_emitter = lambda name: vars_access[name].emit(em)

        for i, (edge, _) in enumerate(matches):
            em.set_extern("token_{0}".format(i), "token_{0}->element".format(i))

        self.line("Net_{0.id} *n = (Net_{0.id}*) net;", tr.net)

        need_tokens = utils.multiset([ edge.get_place() for edge, instrs in matches ])

        for place, count in need_tokens.items():
            self.line("if (n->place_{0.id}.size() < {1}) return false;", place, count)

        em.set_extern("fail", "return false;")
        for i in initcode:
            i.emit(em, self)

        for i, (edge, instrs) in enumerate(matches):
            self.line("// Edge id={0.id} expr={0.expr}", edge)
            place_t = self.emit_type(edge.get_place_type())
            place_id = edge.get_place().id
            token = "token_{0}".format(i)
            self.line("CaToken<{0} > *{1} = n->place_{2}.begin();", place_t, token, place_id)
            em.set_extern("fail", "{0} = {0}->next; continue;".format(token))
            self.do_begin()

            checks = [ "{0} == token_{1}".format(token, j)
                        for j, (e, _) in enumerate(matches[:i])
                        if edge.get_place() == e.get_place() ]
            if checks:
                self.if_begin(" || ".join(checks))
                self.line("{0} = {0}->next;", token)
                self.line("continue;")
                self.block_end()

            for instr in instrs:
                instr.emit(em, self)
        for edge in tr.get_packing_edges_in():
            need = need_tokens.get(edge.get_place(), 0)
            self.if_begin("n->place_{0.id}.size() < {1} + {2}".format(edge.get_place(), need, edge.limit.emit(em)))
            if matches:
                self.line("token_{0} = token_{0}->next;", len(matches) - 1)
                self.line("continue;")
            else:
                self.line("return false;")
            self.block_end()

        self.block_begin()
        self.add_writer(fire_code)
        self.block_end()

        for i, (edge, instrs) in reversed(list(enumerate(matches))):
            self.line("token_{0} = token_{0}->next;", i)
            self.do_end("token_{0} != n->place_{1.id}.begin()".format(i, edge.get_place()))

    def write_extern_types_functions(self):
        decls = {
                 "getstring" : "std::string {0.name}_getstring({0.rawtype} &obj)",
                 "getsize" : "size_t {0.name}_getsize({0.rawtype} &obj)",
                 "pack" : "void {0.name}_pack(CaPacker &packer, {0.rawtype} &obj)",
                 "unpack" : "{0.rawtype} {0.name}_unpack(CaUnpacker &unpacker)"
        }
        def write_fn(etype, name):
            source = ("*{0}/{1}".format(etype.get_name(), name), 1)
            self.write_function(decls[name].format(etype), etype.get_code(name), source)

        for etype in self.project.get_extern_types():
            if etype.has_code("getstring"):
                write_fn(etype, "getstring")
            if etype.get_transport_mode() == "Custom":
                if not etype.has_code("getsize") or not etype.has_code("pack") or not etype.has_code("unpack"):
                    raise utils.PtpException("Extern type has custom transport mode but getsize/pack/unpack missing.")
                write_fn(etype, "getsize")
                write_fn(etype, "pack")
                write_fn(etype, "unpack")

    def build(self):
        self.write_header()
        self.write_parameters()
        self.write_extern_types_functions()
        self.write_types()
        self.write_user_functions()
        for net in self.project.nets:
            self.build_net_class(net)
        for net in self.project.nets:
            self.build_net_functions(net)
        self.write_main()

    def write_spawn(self, net):
        self.line("CaNet * spawn_{0.id}(CaThread *thread, CaNetDef *def, int id, CaNet *parent_net) {{", net)
        self.indent_push()
        self.line("Net_{0.id} *net = new Net_{0.id}(id, id % thread->get_process_count(), def, thread, parent_net);", net)
        self.line("CaContext ctx(thread, net);")
        self.line("int pid = thread->get_process_id();")
        for area in net.areas:
            self.line("std::vector<int> area_{0.id} = {1};", area, area.expr.emit(self.emitter))
        for place in net.places:
            if not (place.init_expression or place.code):
                continue
            areas = place.get_areas()
            if areas == []:
                self.if_begin("pid == net->get_main_process_id()")
            else:
                conditions = [ "std::find(area_{0.id}.begin(), area_{0.id}.end(), pid)!=area_{0.id}.end()"
                              .format(area) for area in areas ]
                self.if_begin(" && ".join(conditions))
            if place.init_expression is not None:
                self.line("net->place_{0.id}.add_all({1});", place, place.init_expression.emit(self.emitter))
            if place.code is not None:
                t = self.emit_type(place.type)
                self.line("std::vector<{0} > tokens;", t)
                self.line("place_user_fn_{0.id}(ctx, tokens);", place)
                self.line("net->place_{0.id}.add_all(tokens);", place)
            self.block_end()

        self.line("return net;")
        self.block_end()

    def reports_method(self, net):
        self.write_method_start("void write_reports_content(CaThread *thread, CaOutput &output)")
        for place in net.places:
            self.line('output.child("place");')
            self.line('output.set("id", {0.id});', place)
            self.block_begin()
            self.line('CaToken<{1} > *t = place_{0.id}.begin();', place, self.emit_type(place.type))
            self.if_begin("t")

            self.do_begin()
            self.line('output.child("token");')
            self.line('output.set("value", {0});', self.code_as_string("t->element", place.type))
            self.line('output.back();')
            self.line("t = t->next;")
            self.do_end("t != place_{0.id}.begin()".format(place))
            self.block_end()
            self.block_end()
            self.line('output.back();')
        for tr in net.transitions:
            self.line("if (enable_check_{0.id}(thread, this)) {{", tr)
            self.indent_push()
            self.line('output.child("enabled");')
            self.line('output.set("id", {0.id});', tr)
            self.line('output.back();')
            self.block_end()
        self.write_method_end()

    def receive_method(self, net):
        self.write_method_start("void receive(int place_pos, CaUnpacker &unpacker)")
        self.line("switch(place_pos) {{")
        for place in net.places:
            if any((edge.target is not None for edge in place.get_edges_in())):
                self.line("case {0}:", place.get_pos_id())
                self.indent_push()
                self.line("place_{0.id}.add({1});", place, self.get_unpack_code(place.type, "unpacker"))
                self.write_activation(self, "this", place.get_transitions_out())
                self.line("break;")
                self.indent_pop()
        self.line("}}")
        self.write_method_end()


    def build_net_class(self, net):

        for place in net.places:
            if place.code is not None:
                self.write_place_user_function(place)

        for tr in net.transitions:
            self.write_transition_forward(tr)

        class_name = "Net_" + str(net.id)
        self.write_class_head(class_name, "CaNet")

        decls = [("id", "int"), ("main_process_id", "int"), ("def", "CaNetDef *"),
                 ("thread", "CaThread *"), ("parent_net", "CaNet *")]
        self.write_constructor(class_name, self.emit_declarations(decls),
                               ["CaNet(id, main_process_id, def, thread, parent_net)"])
        self.write_method_end()

        for place in net.places:
            self.write_var_decl("place_" + str(place.id), "CaPlace<{0} >".format(self.emit_type(place.type)))

        self.reports_method(net)
        self.receive_method(net)
        self.write_class_end()

    def build_net_functions(self, net):

        self.write_spawn(net)

        for tr in net.transitions:
            self.write_transition(tr)

    def emit_type(self, t):
        return self.emitter.emit_type(t)

    def code_as_string(self, expr, t):
        if t.name == "":
            return "({0}).as_string()".format(expr)
        if len(t.args) == 0:
            etype = self.project.get_extern_type(t.name)
            if etype:
                if etype.has_code("getstring"):
                    return "{1}_getstring({0})".format(expr, etype.name)
                else:
                    return self.emitter.const_string(etype.name);
        if t == t_string:
            return expr
        if t.name == "Array" and len(t.args) == 1:
            return "array_{0}_as_string({1})".format(t.args[0].get_safe_name(), expr)
        if t == t_double:
            return "ca_double_to_string({0})".format(expr)
        if t == t_float:
            return "ca_float_to_string({0})".format(expr)
        if t == t_bool:
            return "ca_bool_to_string({0})".format(expr)
        return "ca_int_to_string({0})".format(expr)

    def emit_declarations(self, decls, reference = False):
        return emit_declarations(self.emitter, decls, reference)